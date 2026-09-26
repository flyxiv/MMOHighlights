"""Projects, images and labels.

Bucket layout, one folder per project:

    <slug>/project.json            name, tasks, classes, label groups
    <slug>/manifest.json           every image with its size
    <slug>/images/<file>           the images
    <slug>/annotations/<file>.json labels for one image
    <slug>/exports/<format>-<time>/

The bucket is the source of truth. A project is pulled into the local index the first time it's opened
by this process; after that reads come from the index and saves are pushed back by the sync worker.
"""

import json
import logging
import mimetypes
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app import exporters
from app.config import Settings
from app.index import Index
from app.schemas import (
    COLORS,
    Annotation,
    AnnotationIn,
    BulkRequest,
    ClassIn,
    ExportRequest,
    ExportResult,
    ImageRow,
    Job,
    LabelClass,
    LabelObject,
    PredictionsIn,
    PredictionsResult,
    Project,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
    ProjectSummary,
    Stats,
    UploadResult,
)
from app.store import BlobStore, make_store

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_BAD_CHARS = re.compile(r'[\x00-\x1f\\:*?"<>|]')


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-_")
    return re.sub(r"-{2,}", "-", s)[:60] or "project"


def check_file(name: str) -> str:
    """Reject image names that could escape the project folder or the local cache."""
    if not name or len(name) > 400 or name.startswith("/") or _BAD_CHARS.search(name):
        raise Invalid(f"Invalid image name: {name!r}")
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise Invalid(f"Invalid image name: {name!r}")
    return name


def clean_name(name: str) -> str:
    """An importable name for a file from a folder or bucket."""
    parts = [_BAD_CHARS.sub("_", p).strip() for p in name.replace("\\", "/").split("/")]
    return "/".join(p for p in parts if p not in ("", ".", ".."))


def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS


def image_size(data: bytes) -> tuple[int, int]:
    """Displayed size: browsers apply EXIF rotation, so a rotated photo's sides are swapped."""
    with Image.open(BytesIO(data)) as im:
        w, h = im.size
        try:
            orientation = im.getexif().get(0x0112)
        except Exception:
            orientation = None
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)


def polygon_bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


class Labeler:
    def __init__(self, settings: Settings, store: BlobStore, index: Index):
        self.settings = settings
        self.store = store
        self.index = index
        self.cache = settings.cache_dir
        self.last_sync_error: str | None = None
        self._loaded: set[str] = set()
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=settings.transfer_workers, thread_name_prefix="transfer")
        # Separate so a big import doesn't queue ahead of page requests.
        self._import_pool = ThreadPoolExecutor(
            max_workers=settings.transfer_workers, thread_name_prefix="import"
        )

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._import_pool.shutdown(wait=False, cancel_futures=True)

    def _lock(self, slug: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(slug, threading.Lock())

    # ------------------------------------------------------------------ projects

    def list_projects(self) -> list[ProjectSummary]:
        dirs = self.store.list_dirs()
        raw = list(self._pool.map(lambda d: (d, self.store.read(f"{d}/project.json")), dirs))
        out = []
        for d, data in raw:
            if data is None:
                continue
            try:
                p = Project.model_validate_json(data)
            except ValueError:
                log.warning("Skipping %s: unreadable project.json", d)
                continue
            done = self.index.stats(p.slug)["done"] if p.slug in self._loaded else None
            out.append(
                ProjectSummary(
                    slug=p.slug,
                    name=p.name,
                    tasks=p.tasks,
                    created_at=p.created_at,
                    image_count=p.image_count,
                    classes=len(p.classes),
                    done=done,
                )
            )
        out.sort(key=lambda s: s.created_at, reverse=True)
        return out

    def create_project(self, req: ProjectCreate) -> ProjectOut:
        slug = slugify(req.name)
        with self._lock(slug):
            if self.store.read(f"{slug}/project.json") is not None:
                raise Conflict(f"A project named “{slug}” already exists.")
            project = Project(
                slug=slug,
                name=req.name.strip(),
                created_at=now(),
                tasks=list(dict.fromkeys(req.tasks)),
                classes=self._merge_classes([], req.classes, set()),
                groups=self._check_groups(req.groups),
            )
            self._write_project(project)
            self.store.write(f"{slug}/manifest.json", json.dumps({"images": []}).encode(), "application/json")
            self.index.set_images(slug, [])
            self._loaded.add(slug)
        return self.project(slug)

    def project(self, slug: str) -> ProjectOut:
        p = self._load(slug)
        return ProjectOut(
            **p.model_dump(),
            storage_uri=self.store.uri(slug),
            stats=Stats(**self.index.stats(slug)),
            pending_sync=self.index.pending_count(slug),
        )

    def update_project(self, slug: str, patch: ProjectPatch) -> ProjectOut:
        p = self._load(slug)
        with self._lock(slug):
            if patch.name is not None:
                p.name = patch.name.strip()
            if patch.tasks is not None:
                p.tasks = list(dict.fromkeys(patch.tasks))
            if patch.classes is not None:
                used = {cid for cid, n in self.index.stats(slug)["class_counts"].items() if n > 0}
                p.classes = self._merge_classes(p.classes, patch.classes, used)
            if patch.groups is not None:
                p.groups = self._check_groups(patch.groups)
            self._write_project(p)
        return self.project(slug)

    def _merge_classes(
        self, current: list[LabelClass], wanted: list[ClassIn], used: set[int]
    ) -> list[LabelClass]:
        by_id = {c.id: c for c in current}
        names = [c.name.strip() for c in wanted]
        if len(set(names)) != len(names):
            raise Invalid("Class names must be unique.")
        kept = {c.id for c in wanted if c.id is not None}
        unknown = kept - by_id.keys()
        if unknown:
            raise Invalid(f"Unknown class id {min(unknown)}.")
        removed = set(by_id) - kept
        in_use = sorted(by_id[i].name for i in removed & used)
        if in_use:
            raise Conflict(f"Can't delete {', '.join(in_use)}: still used on some images.")
        next_id = max(by_id, default=-1) + 1
        out = []
        for c in wanted:
            if c.id is None:
                color = c.color or COLORS[next_id % len(COLORS)]
                out.append(LabelClass(id=next_id, name=c.name.strip(), color=color))
                next_id += 1
            else:
                old = by_id[c.id]
                out.append(LabelClass(id=c.id, name=c.name.strip(), color=c.color or old.color))
        return out

    @staticmethod
    def _check_groups(groups):
        names = [g.name.strip() for g in groups]
        if len(set(names)) != len(names):
            raise Invalid("Label group names must be unique.")
        return groups

    def _write_project(self, p: Project) -> None:
        self.store.write(f"{p.slug}/project.json", p.model_dump_json(indent=2).encode(), "application/json")
        self.index.put_project(p.slug, p.model_dump(mode="json"))

    def _load(self, slug: str) -> Project:
        if slug in self._loaded:
            data = self.index.get_project(slug)
            if data is not None:
                return Project.model_validate(data)
        with self._lock(slug):
            if slug not in self._loaded:
                self._pull(slug)
                self._loaded.add(slug)
        return Project.model_validate(self.index.get_project(slug))

    def _pull(self, slug: str) -> None:
        """Bring the local index up to date with the bucket, downloading only changed labels."""
        if slugify(slug) != slug:
            raise NotFound("No such project.")
        started = time.monotonic()
        raw = self.store.read(f"{slug}/project.json")
        if raw is None:
            raise NotFound(f"No project “{slug}” in {self.store.uri()}.")
        project = Project.model_validate_json(raw)
        self.index.put_project(slug, project.model_dump(mode="json"))

        manifest = self.store.read(f"{slug}/manifest.json")
        images = json.loads(manifest)["images"] if manifest else []
        self.index.set_images(slug, [(i["file"], i["width"], i["height"]) for i in images])

        prefix = "annotations/"
        remote = {
            b.name[len(slug) + 1 + len(prefix) : -len(".json")]: b
            for b in self.store.list_blobs(f"{slug}/{prefix}")
            if b.name.endswith(".json")
        }
        local = self.index.generations(slug)
        stale = [
            (f, b)
            for f, b in remote.items()
            if not local.get(f, (None, False))[1] and local.get(f, (None, False))[0] != b.generation
        ]

        def fetch(item):
            f, b = item
            data = self.store.read(b.name)
            if data is not None:
                self.index.put_remote_annotation(slug, f, json.loads(data), b.generation)

        list(self._pool.map(fetch, stale))
        for f, (generation, dirty) in local.items():
            if f not in remote and generation is not None and not dirty:
                self.index.delete_annotation_if_clean(slug, f)
        log.info(
            "Pulled %s: %d images, %d labels (%d downloaded) in %.1fs",
            slug,
            len(images),
            len(remote),
            len(stale),
            time.monotonic() - started,
        )

    # ------------------------------------------------------------------ images

    def images(self, slug: str) -> list[ImageRow]:
        self._load(slug)
        return [
            ImageRow(file=f, width=w, height=h, status=s, objects=n, suggested=ns, labels=json.loads(labels))
            for f, w, h, s, n, ns, labels in self.index.image_rows(slug)
        ]

    def _size(self, slug: str, file: str) -> tuple[int, int]:
        self._load(slug)
        size = self.index.image(slug, check_file(file))
        if size is None:
            raise NotFound(f"No image “{file}” in this project.")
        return size

    def image_path(self, slug: str, file: str) -> Path:
        self._size(slug, file)
        path = self.cache.joinpath("images", slug, *file.split("/"))
        if not path.exists():
            self.store.download(f"{slug}/images/{file}", path)
        return path

    def thumb_path(self, slug: str, file: str) -> Path:
        path = self.cache.joinpath("thumbs", slug, *file.split("/")).with_suffix(".webp")
        if path.exists():
            return path
        src = self.image_path(slug, file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((self.settings.thumb_width, self.settings.thumb_width * 2))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            tmp = path.with_name(path.name + ".part")
            im.save(tmp, "WEBP", quality=72)
        tmp.replace(path)
        return path

    def _add_image(self, slug: str, name: str, data: bytes) -> None:
        """Store one image under an already checked, unused name."""
        try:
            w, h = image_size(data)
        except (UnidentifiedImageError, OSError) as e:
            raise Invalid(f"{name}: not a readable image") from e
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.store.write(f"{slug}/images/{name}", data, content_type)
        cached = self.cache.joinpath("images", slug, *name.split("/"))
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        self.index.add_image(slug, name, w, h)

    def _write_manifest(self, slug: str) -> None:
        with self._lock(slug):
            rows = self.index.manifest(slug)
            body = {"images": [{"file": f, "width": w, "height": h} for f, w, h in rows]}
            self.store.write(f"{slug}/manifest.json", json.dumps(body).encode(), "application/json")
            p = Project.model_validate(self.index.get_project(slug))
            p.image_count = len(rows)
            self._write_project(p)

    def upload(self, slug: str, files: list[tuple[str, bytes]]) -> UploadResult:
        self._load(slug)
        existing = self.index.image_files(slug)
        added = skipped = 0
        errors: list[str] = []
        for raw_name, data in files:
            if not is_image(raw_name):
                errors.append(f"{raw_name}: not an image file")
                continue
            try:
                name = check_file(clean_name(raw_name))
                if name in existing:
                    skipped += 1
                    continue
                self._add_image(slug, name, data)
                existing.add(name)
                added += 1
            except Invalid as e:
                errors.append(str(e))
        if added:
            self._write_manifest(slug)
        return UploadResult(added=added, skipped=skipped, errors=errors[:20])

    def start_import(self, slug: str, source: str) -> Job:
        self._load(slug)
        source = source.strip()
        if not source.startswith("gs://") and not Path(source).is_dir():
            raise Invalid(f"No folder at {source} on this machine.")
        job = Job(id=uuid.uuid4().hex[:12], slug=slug, source=source)
        self._jobs[job.id] = job
        threading.Thread(target=self._run_import, args=(job,), name=f"import-{job.id}", daemon=True).start()
        return job

    def job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFound("No such import.")
        return job

    def jobs(self, slug: str) -> list[Job]:
        return [j for j in self._jobs.values() if j.slug == slug]

    def _run_import(self, job: Job) -> None:
        slug = job.slug
        try:
            src = make_store(job.source)
            blobs = [b for b in src.list_blobs() if is_image(b.name)]
            job.total = len(blobs)
            claimed = self.index.image_files(slug)
            lock = threading.Lock()

            def one(b) -> None:
                try:
                    name = check_file(clean_name(b.name))
                    with lock:
                        fresh = name not in claimed
                        claimed.add(name)
                    if fresh:
                        data = src.read(b.name)
                        if data is None:
                            raise Invalid("disappeared during the import")
                        self._add_image(slug, name, data)
                    with lock:
                        job.processed += 1
                        job.added += fresh
                        job.skipped += not fresh
                except Exception as e:  # one bad file shouldn't stop the import
                    with lock:
                        job.processed += 1
                        if len(job.errors) < 20:
                            job.errors.append(f"{b.name}: {e}")

            last_manifest = time.monotonic()
            for _ in self._import_pool.map(one, blobs):
                # Save the manifest now and then so a long import survives a restart.
                if job.added and time.monotonic() - last_manifest > 30:
                    self._write_manifest(slug)
                    last_manifest = time.monotonic()
            if job.added:
                self._write_manifest(slug)
            job.state = "done"
            job.message = f"Imported {job.added} images" + (f", skipped {job.skipped}" if job.skipped else "")
        except Exception as e:
            log.exception("Import %s failed", job.id)
            job.state = "failed"
            job.message = str(e)
            if job.added:
                self._write_manifest(slug)

    # ------------------------------------------------------------------ labels

    def annotation(self, slug: str, file: str) -> Annotation:
        self._size(slug, file)
        data = self.index.get_annotation(slug, file)
        return Annotation.model_validate(data) if data else Annotation(file=file)

    def _validate(self, p: Project, size: tuple[int, int], ann: AnnotationIn) -> AnnotationIn:
        w, h = size
        class_ids = {c.id for c in p.classes}
        groups = {g.name: g for g in p.groups}
        for group, value in ann.labels.items():
            if group not in groups:
                raise Invalid(f"Unknown label group “{group}”.")
            if value not in groups[group].options:
                raise Invalid(f"“{value}” isn't an option of {group}.")
        objects: list[LabelObject] = []
        seen: set[str] = set()
        for o in ann.objects:
            if o.class_id not in class_ids:
                raise Invalid(f"Unknown class id {o.class_id}.")
            if o.id in seen:
                raise Invalid(f"Duplicate object id {o.id}.")
            seen.add(o.id)
            if o.type == "polygon":
                if not o.points or len(o.points) < 3:
                    raise Invalid("A polygon needs at least 3 points.")
                pts = [(min(max(x, 0), w), min(max(y, 0), h)) for x, y in o.points]
                o = o.model_copy(update={"points": pts, "bbox": polygon_bbox(pts)})
            else:
                x, y, bw, bh = o.bbox
                x0, y0 = min(max(x, 0), w), min(max(y, 0), h)
                x1, y1 = min(max(x + bw, 0), w), min(max(y + bh, 0), h)
                if x1 - x0 < 1 or y1 - y0 < 1:
                    raise Invalid("Boxes must be at least 1 pixel wide and tall inside the image.")
                o = o.model_copy(update={"bbox": (x0, y0, x1 - x0, y1 - y0), "points": None})
            objects.append(o)
        return ann.model_copy(update={"objects": objects})

    def save_annotation(self, slug: str, file: str, ann: AnnotationIn) -> Annotation:
        p = self._load(slug)
        ann = self._validate(p, self._size(slug, file), ann)
        out = Annotation(file=file, updated_at=now(), **ann.model_dump())
        self.index.save_annotation(slug, file, out.model_dump(mode="json"))
        return out

    def bulk(self, slug: str, req: BulkRequest) -> int:
        p = self._load(slug)
        groups = {g.name: g for g in p.groups}
        for group, value in req.labels.items():
            if group not in groups:
                raise Invalid(f"Unknown label group “{group}”.")
            if value is not None and value not in groups[group].options:
                raise Invalid(f"“{value}” isn't an option of {group}.")
        files = self.index.image_files(slug)
        missing = [f for f in req.files if f not in files]
        if missing:
            raise NotFound(f"No image “{missing[0]}” in this project.")
        for f in req.files:
            ann = self.annotation(slug, f)
            labels = dict(ann.labels)
            for group, value in req.labels.items():
                if value is None:
                    labels.pop(group, None)
                else:
                    labels[group] = value
            update = {"labels": labels}
            if req.status is not None:
                update["status"] = req.status
            out = ann.model_copy(update={**update, "updated_at": now()})
            self.index.save_annotation(slug, f, out.model_dump(mode="json"))
        return len(req.files)

    def apply_predictions(self, slug: str, req: PredictionsIn) -> PredictionsResult:
        """Add model output as suggestions. Images already marked done are left alone."""
        p = self._load(slug)
        by_name = {c.name: c.id for c in p.classes}
        updated = skipped = 0
        for pred in req.predictions:
            size = self._size(slug, pred.file)
            ann = self.annotation(slug, pred.file)
            if ann.status == "done":
                skipped += 1
                continue
            objects = [o for o in ann.objects if not (req.replace and o.source == "model" and not o.accepted)]
            for po in pred.objects:
                cid = po.class_id if po.class_id is not None else by_name.get(po.class_name or "")
                if cid is None:
                    raise Invalid(f"{pred.file}: unknown class {po.class_name!r}.")
                oid = f"m{uuid.uuid4().hex[:10]}"
                if po.points:
                    obj = LabelObject(
                        id=oid,
                        class_id=cid,
                        type="polygon",
                        points=po.points,
                        source="model",
                        score=po.score,
                        accepted=False,
                    )
                elif po.bbox:
                    obj = LabelObject(
                        id=oid, class_id=cid, bbox=po.bbox, source="model", score=po.score, accepted=False
                    )
                else:
                    raise Invalid(f"{pred.file}: a prediction needs a bbox or points.")
                objects.append(obj)
            fixed = self._validate(
                p, size, AnnotationIn(status=ann.status, labels=ann.labels, objects=objects)
            )
            out = Annotation(file=pred.file, updated_at=now(), **fixed.model_dump())
            self.index.save_annotation(slug, pred.file, out.model_dump(mode="json"))
            updated += 1
        return PredictionsResult(updated=updated, skipped=skipped)

    # ------------------------------------------------------------------ export

    def export(self, slug: str, req: ExportRequest) -> ExportResult:
        p = self._load(slug)
        anns = self.index.annotations(slug)
        images = [
            (f, w, h, anns[f])
            for f, w, h in self.index.manifest(slug)
            if f in anns and (anns[f].get("status") == "done" or req.include_unfinished)
        ]
        if not images:
            raise Invalid("Nothing to export yet. Mark images done with D first.")
        folder = f"{slug}/exports/{req.format}-{now():%Y%m%d-%H%M%S}"
        files, n_objects = (exporters.yolo if req.format == "yolo" else exporters.coco)(
            p, images, self.store.uri(f"{slug}/images")
        )
        list(
            self._pool.map(
                lambda kv: self.store.write(f"{folder}/{kv[0]}", kv[1][0], kv[1][1]), files.items()
            )
        )
        return ExportResult(
            uri=self.store.uri(folder), format=req.format, images=len(images), objects=n_objects
        )

    # ------------------------------------------------------------------ sync

    def push_pending(self) -> int:
        """Upload saved labels to the bucket. Returns how many were pushed; stops at the first error."""
        pushed = 0
        for item in self.index.pending():
            try:
                gen = self.store.write(
                    f"{item.slug}/annotations/{item.file}.json", item.data.encode("utf-8"), "application/json"
                )
            except Exception as e:
                self.last_sync_error = f"{type(e).__name__}: {e}"
                log.warning("Label sync failed: %s", self.last_sync_error)
                return pushed
            self.index.mark_pushed(item, gen)
            pushed += 1
        self.last_sync_error = None
        return pushed
