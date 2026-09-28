"""Datasets in the uniform layout (datasets/STRUCTURE.md in RaidDesigner, sections 1, 3-5a).

    gs://ai_datasets_jyn/datasets/<name>/
        dataset.json                  card; absent until the first release
        raw/labeler/<date>/<id>.<ext> images added here
        releases/vN/                  immutable: manifest.jsonl, classes.json, splits/, stats.json
        labeling/                     this tool's mutable work area
            project.json              base_release, tasks, card draft
            classes.json              full vocabulary for the next release
            labels/<id>.json          complete labels + status for each touched sample

The bucket is the source of truth. A dataset is pulled into the local index the first time it's
opened by this process; after that reads come from the index and saves are pushed back by the sync
worker. Releases are only written through cut_release (vendored from RaidDesigner's
dataset_format.py, the single implementation of the spec) and are never modified.
"""

import hashlib
import json
import logging
import mimetypes
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.index import CHOICES, SHAPES, Index
from app.schemas import (
    EDITABLE,
    NAME_PATTERN,
    TASK_PATTERN,
    BulkRequest,
    Dataset,
    DatasetCreate,
    DatasetSummary,
    Job,
    LabelingPatch,
    PredictionsIn,
    PredictionsResult,
    ReleaseRequest,
    ReleaseResult,
    Sample,
    SampleRow,
    SampleSave,
    Stats,
    TaskSpec,
    UploadResult,
)
from app.store import BlobStore, make_store
from app.vendor.dataset_format import cut_release

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
NAME_RE = re.compile(NAME_PATTERN)
TASK_RE = re.compile(TASK_PATTERN)
ID_RE = re.compile(r"^[a-z0-9_]{4,64}$")


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_image(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in IMAGE_EXTS


def image_size(data: bytes) -> tuple[int, int]:
    """Displayed size: browsers apply EXIF rotation, so a rotated photo's sides are swapped."""
    with Image.open(BytesIO(data)) as im:
        w, h = im.size
        try:
            orientation = im.getexif().get(0x0112)
        except Exception:
            orientation = None
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)


def sample_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def check_relpath(p: str) -> str:
    if not p or p.startswith("/") or "\\" in p or any(x in ("", ".", "..") for x in p.split("/")):
        raise Invalid(f"Bad path in the dataset: {p!r}")
    return p


def display_name(sid: str, meta: dict | None) -> str:
    original = (meta or {}).get("original_path")
    return PurePosixPath(str(original).replace("\\", "/")).name if original else sid


SIDECAR = "frames.json"
HEX16 = re.compile(r"^[0-9a-f]{16}$")


def parse_sidecar(folder: str, data: bytes, errors: list[str]) -> dict[str, dict]:
    """frames.json (spec 5a): {file name: {"parent_id", "source", "t_s"}} for frames cut from a video.

    Returns {folder/file: meta to merge}. Bad entries are reported and skipped; the frame still imports.
    """
    where = f"{folder}/{SIDECAR}" if folder else SIDECAR
    try:
        doc = json.loads(data)
    except ValueError as e:
        errors.append(f"{where}: not valid JSON ({e})")
        return {}
    if not isinstance(doc, dict):
        errors.append(f"{where}: must map file names to {{parent_id, source, t_s}}")
        return {}
    out = {}
    for fname, entry in doc.items():
        if not isinstance(entry, dict):
            errors.append(f"{where}: {fname}: entry must be an object")
            continue
        meta: dict[str, Any] = {}
        pid, src, t = entry.get("parent_id"), entry.get("source"), entry.get("t_s")
        if pid is not None:
            if not (isinstance(pid, str) and HEX16.match(pid)):
                errors.append(f"{where}: {fname}: parent_id must be 16 lowercase hex characters")
                continue
            meta["parent_id"] = pid
        if src is not None:
            try:
                meta["source"] = check_relpath(src) if isinstance(src, str) else None
            except Invalid:
                meta["source"] = None
            if meta["source"] is None:
                errors.append(f"{where}: {fname}: source must be a dataset-relative path")
                continue
        if t is not None:
            if not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0:
                errors.append(f"{where}: {fname}: t_s must be a non-negative number")
                continue
            meta["t_s"] = float(t)
        out[f"{folder}/{fname}" if folder else fname] = meta
    return out


def _folder(path: str) -> str:
    """Folder part of a "/"-separated relative path ("" at the root)."""
    p = path.replace("\\", "/")
    return p.rsplit("/", 1)[0] if "/" in p else ""


def _r(v: float) -> float:
    return round(float(v), 1)


def _tasks(ds: dict) -> dict:
    return {**((ds["card"] or {}).get("tasks") or {}), **(ds["project"].get("tasks") or {})}


class Labeler:
    def __init__(self, settings: Settings, store: BlobStore, index: Index):
        self.settings = settings
        self.bucket = store
        self.store = store.child("datasets")
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

    def _lock(self, name: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(name, threading.Lock())

    def _read_json(self, path: str) -> Any:
        data = self.store.read(path)
        return json.loads(data) if data is not None else None

    def _write_json(self, path: str, obj: Any) -> str:
        return self.store.write(
            path, json.dumps(obj, ensure_ascii=False, indent=2).encode(), "application/json"
        )

    # ------------------------------------------------------------------ datasets

    def list_datasets(self) -> list[DatasetSummary]:
        names = [n for n in self.store.list_dirs() if NAME_RE.match(n)]

        def one(n: str):
            return n, self._read_json(f"{n}/dataset.json"), self._read_json(f"{n}/labeling/project.json")

        out = []
        for n, card, project in self._pool.map(one, names):
            if card is None and project is None:
                continue
            src = card or (project or {}).get("card") or {}
            latest = (card or {}).get("latest")
            tasks = {**((card or {}).get("tasks") or {}), **((project or {}).get("tasks") or {})}
            out.append(
                DatasetSummary(
                    name=n,
                    title=src.get("title") or n,
                    tasks={t: TaskSpec.model_validate(s) for t, s in tasks.items()},
                    latest=latest,
                    samples=(card or {}).get("versions", {}).get(latest, {}).get("samples")
                    if latest
                    else None,
                    labeling=project is not None,
                    created=src.get("created"),
                )
            )
        return out

    def create_dataset(self, req: DatasetCreate) -> Dataset:
        name = req.name
        with self._lock(name):
            if self.store.stat(f"{name}/dataset.json") or self.store.stat(f"{name}/labeling/project.json"):
                raise Conflict(f"A dataset named “{name}” already exists.")
            tasks = self._check_tasks(req.tasks)
            classes = {
                t: self._check_names(t, req.classes.get(t, []))
                for t, s in tasks.items()
                if s.type in EDITABLE
            }
            project = {
                "base_release": None,
                "tasks": {t: s.model_dump(exclude_none=True) for t, s in tasks.items()},
                "tool": "labeler",
                "updated_at": now_iso(),
                "card": req.model_dump(exclude={"tasks", "classes"}, exclude_none=True),
            }
            self._write_json(f"{name}/labeling/classes.json", classes)
            self._write_json(f"{name}/labeling/project.json", project)
            self.index.put_dataset(name, card=None, project=project, classes=classes, base_classes={})
            self.index.set_samples(name, [], None)
            self._loaded.add(name)
        return self.dataset(name)

    @staticmethod
    def _check_tasks(tasks: dict[str, TaskSpec]) -> dict[str, TaskSpec]:
        for t in tasks:
            if not TASK_RE.match(t):
                raise Invalid(f"Task names are snake_case ASCII: {t!r}")
        return tasks

    @staticmethod
    def _check_names(task: str, names: list[str]) -> list[str]:
        clean = [n.strip() for n in names]
        if any(not n or len(n) > 80 for n in clean):
            raise Invalid(f"Class names in {task} must be 1–80 characters.")
        if len(set(clean)) != len(clean):
            raise Invalid(f"Class names in {task} must be unique.")
        return clean

    def _load(self, name: str) -> dict:
        if not NAME_RE.match(name):
            raise NotFound("No such dataset.")
        if name not in self._loaded:
            with self._lock(name):
                if name not in self._loaded:
                    self._pull(name)
                    self._loaded.add(name)
        ds = self.index.dataset(name)
        if ds is None:
            raise NotFound(f"No dataset “{name}”.")
        return ds

    def _pull(self, name: str) -> None:
        """Bring the local index up to date with the bucket, downloading only what changed."""
        started = time.monotonic()
        card = self._read_json(f"{name}/dataset.json")
        project = self._read_json(f"{name}/labeling/project.json")
        if project is None:
            if card is None:
                raise NotFound(f"No dataset “{name}” in {self.store.uri()}.")
            # First time anyone labels this dataset: start from its latest release.
            base = card.get("latest")
            project = {
                "base_release": base,
                "tasks": card.get("tasks", {}),
                "tool": "labeler",
                "updated_at": now_iso(),
            }
            base_classes = (self._read_json(f"{name}/releases/{base}/classes.json") or {}) if base else {}
            classes = base_classes
            self._write_json(f"{name}/labeling/classes.json", classes)
            self._write_json(f"{name}/labeling/project.json", project)
        else:
            base = project.get("base_release")
            base_classes = (self._read_json(f"{name}/releases/{base}/classes.json") or {}) if base else {}
            classes = self._read_json(f"{name}/labeling/classes.json") or base_classes
        self.index.put_dataset(name, card=card, project=project, classes=classes, base_classes=base_classes)

        if base:
            path = f"{name}/releases/{base}/manifest.jsonl"
            info = self.store.stat(path)
            if info is None:
                raise Invalid(f"Release {base} of {name} has no manifest.jsonl.")
            key = f"{base}:{info.generation}"
            if self.index.manifest_key(name) != key:
                raw = self.store.read(path) or b""
                lines = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
                self.index.set_samples(name, lines, key)
        elif self.index.manifest_key(name) is not None:
            self.index.set_samples(name, [], None)

        prefix = f"{name}/labeling/labels/"
        remote = {
            b.name[len(prefix) : -len(".json")]: b
            for b in self.store.list_blobs(prefix)
            if b.name.endswith(".json")
        }
        local = self.index.generations(name)
        stale = [
            (sid, b)
            for sid, b in remote.items()
            if not local.get(sid, (None, False))[1] and local.get(sid, (None, False))[0] != b.generation
        ]

        def fetch(item):
            sid, b = item
            data = self.store.read(b.name)
            if data is not None:
                self.index.put_remote_work(name, sid, json.loads(data), b.generation)

        list(self._pool.map(fetch, stale))
        for sid, (generation, dirty) in local.items():
            if sid not in remote and generation is not None and not dirty:
                self.index.delete_work_if_clean(name, sid)
        log.info(
            "Pulled %s (base %s): %d label files, %d downloaded, in %.1fs",
            name,
            base,
            len(remote),
            len(stale),
            time.monotonic() - started,
        )

    def _releases(self, name: str) -> list[str]:
        vs = [v for v in self.store.list_dirs(f"{name}/releases") if re.match(r"^v[0-9]+$", v)]
        return sorted(vs, key=lambda v: int(v[1:]))

    def dataset(self, name: str) -> Dataset:
        ds = self._load(name)
        card, project = ds["card"], ds["project"]
        src = card or project.get("card") or {}
        releases = self._releases(name)
        nums = [int(v[1:]) for v in releases] + [int(v[1:]) for v in (card or {}).get("versions", {})]
        return Dataset(
            name=name,
            title=src.get("title") or name,
            description=src.get("description"),
            tasks={t: TaskSpec.model_validate(s) for t, s in _tasks(ds).items()},
            classes=ds["classes"],
            base_release=project.get("base_release"),
            latest=(card or {}).get("latest"),
            releases=releases,
            next_release=f"v{max(nums, default=0) + 1}",
            storage_uri=self.store.uri(name),
            stats=self._stats(name),
            pending_sync=self.index.pending_count(name),
        )

    def update_labeling(self, name: str, patch: LabelingPatch) -> Dataset:
        ds = self._load(name)
        with self._lock(name):
            project, classes, base_classes = ds["project"], dict(ds["classes"]), ds["base_classes"]
            card_tasks = (ds["card"] or {}).get("tasks") or {}
            used = self._used_classes(name)
            if patch.tasks is not None:
                tasks = self._check_tasks(patch.tasks)
                for t, spec in (project.get("tasks") or {}).items():
                    if t not in tasks:
                        if t in card_tasks:
                            raise Conflict(f"{t} is part of a release and can't be removed.")
                        if used.get(t):
                            raise Conflict(f"{t} is used on some images and can't be removed.")
                    elif tasks[t].type != spec.get("type") and (t in card_tasks or used.get(t)):
                        raise Conflict(f"{t} already has labels; its type can't change.")
                project = {**project, "tasks": {t: s.model_dump(exclude_none=True) for t, s in tasks.items()}}
                for t, s in tasks.items():
                    if s.type in EDITABLE:
                        classes.setdefault(t, [])
                classes = {t: c for t, c in classes.items() if t in tasks or t in base_classes}
            if patch.classes is not None:
                for t, names in patch.classes.items():
                    names = self._check_names(t, names)
                    base = base_classes.get(t, [])
                    if names[: len(base)] != base:
                        raise Conflict(
                            f"Released classes of {t} must stay first and in order: {', '.join(base)}"
                        )
                    gone = sorted((set(classes.get(t, [])) - set(names)) & used.get(t, set()))
                    if gone:
                        raise Conflict(f"Can't delete {', '.join(gone)}: still used on some images.")
                    classes[t] = names
            project = {**project, "updated_at": now_iso()}
            self._write_json(f"{name}/labeling/classes.json", classes)
            self._write_json(f"{name}/labeling/project.json", project)
            self.index.set_project(name, project)
            self.index.set_classes(name, classes)
        return self.dataset(name)

    def _used_classes(self, name: str) -> dict[str, set[str]]:
        used: dict[str, set[str]] = {}
        work = self.index.all_work(name)
        docs = [w.get("labels", {}) for w in work] + [w.get("suggestions", {}) for w in work]
        docs += [s.get("labels", {}) for s in self.index.base_samples(name)]
        for labels in docs:
            for task, lab in labels.items():
                v = lab.get("value")
                if lab.get("type") == "class" and isinstance(v, str):
                    used.setdefault(task, set()).add(v)
                elif lab.get("type") == "multilabel" and isinstance(v, list):
                    used.setdefault(task, set()).update(v)
                elif lab.get("type") in SHAPES and isinstance(v, list):
                    used.setdefault(task, set()).update(it.get("class") for it in v if isinstance(it, dict))
        return used

    # ------------------------------------------------------------------ samples

    @staticmethod
    def _effective(base: dict | None, work: dict | None) -> tuple[str, dict, dict, dict]:
        """(status, labels, suggestions, meta) as the editor sees them."""
        base_meta = (base or {}).get("meta") or {}
        if work:
            meta = {**base_meta, **(work.get("meta") or {})}
            return work.get("status", "todo"), work.get("labels", {}), work.get("suggestions", {}), meta
        status = "done" if base_meta.get("reviewed") else "todo"
        return status, (base or {}).get("labels", {}), {}, base_meta

    def rows(self, name: str) -> list[SampleRow]:
        self._load(name)
        out = []
        for row in self.index.rows(name):
            sid, _image, split, b_obj, b_lsum, reviewed, b_data, w_status, w_obj, w_sug, w_lsum, w_data = row
            meta = json.loads(w_data).get("meta") if w_data else None
            if meta is None and b_data:
                meta = json.loads(b_data).get("meta")
            touched = w_status is not None
            out.append(
                SampleRow(
                    id=sid,
                    name=display_name(sid, meta),
                    status=w_status if touched else ("done" if reviewed else "todo"),
                    objects=w_obj if touched else b_obj,
                    suggested=w_sug if touched else 0,
                    labels=json.loads(w_lsum if touched else b_lsum),
                    split=split,
                    new=b_data is None,
                    reviewed=bool(reviewed),
                )
            )
        return out

    def _stats(self, name: str) -> dict:
        counts = {"todo": 0, "review": 0, "done": 0, "excluded": 0}
        class_counts: dict[str, dict[str, int]] = {}
        total = new = edited = 0
        for row in self.index.rows(name):
            reviewed, b_data, w_status, w_objects, w_lsum, w_data = (
                row[5],
                row[6],
                row[7],
                row[8],
                row[10],
                row[11],
            )
            total += 1
            new += b_data is None
            # New images get a todo file on import; count only files that carry an edit.
            has_edit = (
                b_data is not None or w_status == "review" or bool(w_objects) or w_lsum not in (None, "{}")
            )
            edited += w_status in ("todo", "review") and has_edit
            counts[w_status if w_status else ("done" if reviewed else "todo")] += 1
            labels = json.loads(w_data or b_data or "{}").get("labels", {})
            for task, lab in labels.items():
                tc = class_counts.setdefault(task, {})
                v = lab.get("value")
                if lab.get("type") == "class" and isinstance(v, str):
                    tc[v] = tc.get(v, 0) + 1
                elif lab.get("type") == "multilabel" and isinstance(v, list):
                    for x in v:
                        tc[x] = tc.get(x, 0) + 1
                elif lab.get("type") in SHAPES and isinstance(v, list):
                    for it in v:
                        tc[it.get("class")] = tc.get(it.get("class"), 0) + 1
        return Stats(
            total=total, new=new, edited_not_done=edited, class_counts=class_counts, **counts
        ).model_dump()

    def _find(self, name: str, sid: str) -> tuple[dict | None, dict | None, str]:
        """(base line, work file, image path) for a sample with an image."""
        self._load(name)
        if not ID_RE.match(sid):
            raise NotFound("No such sample.")
        base = self.index.base_sample(name, sid)
        work = self.index.work(name, sid)
        files = (base or {}).get("files") or (work or {}).get("files") or {}
        image = files.get("image")
        if not isinstance(image, str):
            raise NotFound(f"No image sample “{sid}” in {name}.")
        return base, work, check_relpath(image)

    def _dims(self, name: str, sid: str, meta: dict, image: str) -> tuple[int, int]:
        if meta.get("width") and meta.get("height"):
            return int(meta["width"]), int(meta["height"])
        cached = self.index.dims(name, sid)
        if cached:
            return cached
        with Image.open(self._file(name, image)) as im:
            w, h = ImageOps.exif_transpose(im).size
        self.index.put_dims(name, sid, w, h)
        return w, h

    def sample(self, name: str, sid: str) -> Sample:
        base, work, image = self._find(name, sid)
        status, labels, suggestions, meta = self._effective(base, work)
        w, h = self._dims(name, sid, meta, image)
        return Sample(
            id=sid,
            name=display_name(sid, meta),
            image=image,
            width=w,
            height=h,
            status=status,
            labels=labels,
            suggestions=suggestions,
            split=(base or {}).get("split", "unsplit"),
            new=base is None,
            meta=meta,
            updated_at=(work or {}).get("updated_at"),
        )

    def _clean(self, ds: dict, labels: dict, size: tuple[int, int], *, suggestions: bool = False) -> dict:
        """Validate editable-task labels against the task types and vocabulary; clamp shapes to the image."""
        tasks = _tasks(ds)
        w, h = size
        out = {}
        for task, lab in labels.items():
            spec = tasks.get(task)
            if spec is None:
                raise Invalid(f"Unknown task “{task}”.")
            t = lab.get("type") if isinstance(lab, dict) else None
            if t != spec.get("type") or t not in EDITABLE:
                raise Invalid(f"{task} is a {spec.get('type')} task.")
            known = set(ds["classes"].get(task, []))
            v = lab.get("value")
            if t == "class":
                if not isinstance(v, str) or v not in known:
                    raise Invalid(f"“{v}” isn't a class of {task}.")
                out[task] = {"type": t, "value": v}
            elif t == "multilabel":
                if not isinstance(v, list) or any(x not in known for x in v):
                    raise Invalid(f"{task}: every value must be one of its classes.")
                out[task] = {"type": t, "value": list(dict.fromkeys(v))}
            else:
                if not isinstance(v, list):
                    raise Invalid(f"{task}: value must be a list.")
                items = []
                for it in v:
                    if not isinstance(it, dict) or it.get("class") not in known:
                        cls = it.get("class") if isinstance(it, dict) else it
                        raise Invalid(f"{task}: “{cls}” isn't one of its classes.")
                    score = it.get("score")
                    extra = {"score": score} if suggestions and isinstance(score, (int, float)) else {}
                    if t == "bbox":
                        try:
                            x1, y1, x2, y2 = (float(c) for c in it.get("xyxy", ()))
                        except (TypeError, ValueError) as e:
                            raise Invalid(f"{task}: xyxy must be 4 numbers.") from e
                        x1, x2 = sorted((min(max(x1, 0), w), min(max(x2, 0), w)))
                        y1, y2 = sorted((min(max(y1, 0), h), min(max(y2, 0), h)))
                        if x2 - x1 < 1 or y2 - y1 < 1:
                            raise Invalid("Boxes must be at least 1 pixel wide and tall inside the image.")
                        items.append(
                            {"class": it["class"], "xyxy": [_r(x1), _r(y1), _r(x2), _r(y2)], **extra}
                        )
                    else:
                        pts = it.get("points") or []
                        if len(pts) < 3:
                            raise Invalid("A polygon needs at least 3 points.")
                        pts = [[_r(min(max(p[0], 0), w)), _r(min(max(p[1], 0), h))] for p in pts]
                        items.append({"class": it["class"], "points": pts, **extra})
                out[task] = {"type": t, "value": items}
        return out

    def _write_sample(
        self,
        name: str,
        sid: str,
        base: dict | None,
        work: dict | None,
        *,
        status: str,
        editable: dict,
        suggestions: dict,
    ) -> dict:
        """Write labeling/labels/<id>.json with the COMPLETE labels (spec 5a)."""
        _, current, _, _ = self._effective(base, work)
        keep = {t: lab for t, lab in current.items() if lab.get("type") not in EDITABLE}
        data: dict[str, Any] = {"id": sid, "status": status, "labels": {**keep, **editable}}
        if suggestions:
            data["suggestions"] = suggestions
        if base is None:
            data["files"] = (work or {}).get("files")
        if (work or {}).get("meta"):
            data["meta"] = work["meta"]
        data["updated_at"] = now_iso()
        self.index.save_work(name, sid, data)
        return data

    def save_sample(self, name: str, sid: str, body: SampleSave) -> Sample:
        ds = self._load(name)
        base, work, image = self._find(name, sid)
        _, _, _, meta = self._effective(base, work)
        size = self._dims(name, sid, meta, image)
        editable = self._clean(ds, body.labels, size)
        suggestions = self._clean(ds, body.suggestions, size, suggestions=True)
        suggestions = {t: lab for t, lab in suggestions.items() if lab["value"]}
        self._write_sample(
            name, sid, base, work, status=body.status, editable=editable, suggestions=suggestions
        )
        return self.sample(name, sid)

    def bulk(self, name: str, req: BulkRequest) -> int:
        ds = self._load(name)
        tasks = _tasks(ds)
        for task, value in req.labels.items():
            t = (tasks.get(task) or {}).get("type")
            if t not in CHOICES:
                raise Invalid(f"{task} isn't a class or multilabel task.")
            if t == "class" and isinstance(value, list):
                raise Invalid(f"{task} takes one value.")
            values = value if isinstance(value, list) else [value] if value is not None else []
            if any(v not in ds["classes"].get(task, []) for v in values):
                raise Invalid(f"Unknown class for {task}.")
        found = [(sid, *self._find(name, sid)) for sid in req.ids]
        for sid, base, work, _ in found:
            status, labels, suggestions, _ = self._effective(base, work)
            editable = {t: lab for t, lab in labels.items() if lab.get("type") in EDITABLE}
            for task, value in req.labels.items():
                t = tasks[task]["type"]
                if value is None:
                    editable.pop(task, None)
                else:
                    editable[task] = {
                        "type": t,
                        "value": value if t == "class" or isinstance(value, list) else [value],
                    }
            self._write_sample(
                name, sid, base, work, status=req.status or status, editable=editable, suggestions=suggestions
            )
        return len(found)

    def apply_predictions(self, name: str, req: PredictionsIn) -> PredictionsResult:
        """Model output becomes suggestions; samples already marked done are left alone."""
        ds = self._load(name)
        updated = skipped = 0
        for p in req.predictions:
            base, work, image = self._find(name, p.id)
            status, labels, _, meta = self._effective(base, work)
            if status == "done":
                skipped += 1
                continue
            suggestions = self._clean(
                ds, p.suggestions, self._dims(name, p.id, meta, image), suggestions=True
            )
            editable = {t: lab for t, lab in labels.items() if lab.get("type") in EDITABLE}
            self._write_sample(
                name, p.id, base, work, status=status, editable=editable, suggestions=suggestions
            )
            updated += 1
        return PredictionsResult(updated=updated, skipped=skipped)

    # ------------------------------------------------------------------ files

    def _file(self, name: str, path: str) -> Path:
        """Local copy of a dataset file, downloaded on first use."""
        local = self.cache.joinpath("files", name, *check_relpath(path).split("/"))
        if not local.exists():
            self.store.download(f"{name}/{path}", local)
        return local

    def image_path(self, name: str, sid: str) -> Path:
        _, _, image = self._find(name, sid)
        return self._file(name, image)

    def thumb_path(self, name: str, sid: str) -> Path:
        path = self.cache.joinpath("thumbs", name, f"{sid}.webp")
        if path.exists():
            return path
        src = self.image_path(name, sid)
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

    def _add_image(
        self,
        name: str,
        original: str,
        data: bytes,
        known: set[str],
        lock: threading.Lock,
        extra_meta: dict | None = None,
    ) -> bool:
        """Store one new image under raw/labeler/<date>/<id>.<ext>. False if it's already in the dataset."""
        sid = sample_id(data)
        with lock:
            if sid in known:
                return False
            known.add(sid)
        try:
            w, h = image_size(data)
        except (UnidentifiedImageError, OSError) as e:
            raise Invalid(f"{original}: not a readable image") from e
        ext = PurePosixPath(original).suffix.lower()
        path = f"raw/labeler/{date.today().isoformat()}/{sid}{ext}"
        self.store.write(f"{name}/{path}", data, mimetypes.guess_type(path)[0] or "application/octet-stream")
        local = self.cache.joinpath("files", name, *path.split("/"))
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        self.index.save_work(
            name,
            sid,
            {
                "id": sid,
                "status": "todo",
                "labels": {},
                "files": {"image": path},
                "meta": {"original_path": original, "width": w, "height": h, **(extra_meta or {})},
                "updated_at": now_iso(),
            },
        )
        return True

    def upload(self, name: str, files: list[tuple[str, bytes]]) -> UploadResult:
        self._load(name)
        known = self.index.sample_ids(name)
        lock = threading.Lock()
        added = skipped = 0
        errors: list[str] = []
        # The page sends each folder's frames.json with every batch of that folder's images.
        frames: dict[str, dict] = {}
        for original, data in files:
            if PurePosixPath(original).name == SIDECAR:
                frames.update(parse_sidecar(_folder(original), data, errors))
        for original, data in files:
            if PurePosixPath(original).name == SIDECAR:
                continue
            if not is_image(original):
                errors.append(f"{original}: not an image file")
                continue
            try:
                if self._add_image(
                    name, original, data, known, lock, frames.get(original.replace("\\", "/"))
                ):
                    added += 1
                else:
                    skipped += 1
            except Invalid as e:
                errors.append(str(e))
        return UploadResult(added=added, skipped=skipped, errors=errors[:20])

    def start_import(self, name: str, source: str) -> Job:
        self._load(name)
        source = source.strip()
        if not source.startswith("gs://") and not Path(source).is_dir():
            raise Invalid(f"No folder at {source} on this machine.")
        job = Job(id=uuid.uuid4().hex[:12], dataset=name, source=source)
        self._jobs[job.id] = job
        threading.Thread(target=self._run_import, args=(job,), name=f"import-{job.id}", daemon=True).start()
        return job

    def job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFound("No such import.")
        return job

    def jobs(self, name: str) -> list[Job]:
        return [j for j in self._jobs.values() if j.dataset == name]

    def _run_import(self, job: Job) -> None:
        try:
            src = make_store(job.source)
            listing = src.list_blobs()
            blobs = [b for b in listing if is_image(b.name)]
            job.total = len(blobs)
            frames: dict[str, dict] = {}
            for b in listing:
                if PurePosixPath(b.name).name == SIDECAR:
                    errs: list[str] = []
                    frames.update(parse_sidecar(_folder(b.name), src.read(b.name) or b"{}", errs))
                    job.errors.extend(errs[: max(0, 20 - len(job.errors))])
            known = self.index.sample_ids(job.dataset)
            lock = threading.Lock()

            def one(b) -> None:
                try:
                    data = src.read(b.name)
                    if data is None:
                        raise Invalid("disappeared during the import")
                    fresh = self._add_image(job.dataset, b.name, data, known, lock, frames.get(b.name))
                    with lock:
                        job.processed += 1
                        job.added += fresh
                        job.skipped += not fresh
                except Exception as e:  # one bad file shouldn't stop the import
                    with lock:
                        job.processed += 1
                        if len(job.errors) < 20:
                            job.errors.append(f"{b.name}: {e}")

            list(self._import_pool.map(one, blobs))
            job.state = "done"
            skipped = f", skipped {job.skipped} already in the dataset" if job.skipped else ""
            job.message = f"Imported {job.added} images{skipped}"
        except Exception as e:
            log.exception("Import %s failed", job.id)
            job.state = "failed"
            job.message = str(e)

    # ------------------------------------------------------------------ releases

    def release(self, name: str, req: ReleaseRequest) -> ReleaseResult:
        self._load(name)
        # The bucket's labeling/ must match what gets released.
        while self.index.pending_count(name):
            if not self.push_pending() and self.last_sync_error:
                raise Conflict(f"Can't reach the bucket to save labels first: {self.last_sync_error}")
        ds = self._load(name)
        with self._lock(name):
            has_base = bool(ds["project"].get("base_release"))
            result = cut_release(
                ds["card"],
                self.index.base_samples(name) if has_base else None,
                ds["base_classes"] if has_base else None,
                ds["project"],
                ds["classes"],
                self.index.all_work(name),
                today=date.today().isoformat(),
                notes=req.notes,
            )
            if result["errors"]:
                raise Invalid("Release not written: " + "; ".join(result["errors"][:5]))
            version = result["version"]
            folder = f"{name}/releases/{version}"
            if self.store.list_blobs(f"{folder}/"):
                raise Conflict(f"{version} already exists in the bucket; releases are never overwritten.")
            self._check_files_exist(name, has_base, result["manifest"])

            manifest = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in result["manifest"])
            classes = json.dumps(result["classes"], ensure_ascii=False, indent=2)
            writes = {
                f"{folder}/manifest.jsonl": (manifest.encode(), "application/x-ndjson"),
                f"{folder}/classes.json": (classes.encode(), "application/json"),
                f"{folder}/stats.json": (
                    json.dumps(result["stats"], indent=2).encode() + b"\n",
                    "application/json",
                ),
            }
            for split in ("train", "val", "test"):
                ids = result["splits"].get(split, [])
                writes[f"{folder}/splits/{split}.txt"] = (
                    "".join(i + "\n" for i in ids).encode(),
                    "text/plain",
                )
            list(self._pool.map(lambda kv: self.store.write(kv[0], *kv[1]), writes.items()))
            # The card and the base pointer move only after the whole release is in place.
            self._write_json(f"{name}/dataset.json", result["card"])
            self._write_json(f"{name}/labeling/project.json", result["project"])
            self._loaded.discard(name)
        self._load(name)
        return ReleaseResult(
            version=version,
            uri=self.store.uri(folder),
            samples=len(result["manifest"]),
            reviewed=sum(1 for line in result["manifest"] if (line.get("meta") or {}).get("reviewed")),
            splits={k: len(v) for k, v in result["splits"].items()},
            warnings=result["warnings"],
        )

    def _check_files_exist(self, name: str, has_base: bool, lines: list[dict]) -> None:
        """New samples' files must be in the bucket (base samples' files were checked when released)."""
        base_ids = {s["id"] for s in self.index.base_samples(name)} if has_base else set()
        needed = {
            p
            for line in lines
            if line["id"] not in base_ids
            for v in line["files"].values()
            for p in (v if isinstance(v, list) else [v])
        }
        if not needed:
            return
        present = {b.name[len(name) + 1 :] for b in self.store.list_blobs(f"{name}/raw/")}
        missing = sorted(p for p in needed if p not in present and self.store.stat(f"{name}/{p}") is None)
        if missing:
            raise Invalid(
                f"Release not written: {len(missing)} files missing in the bucket, e.g. {missing[0]}"
            )

    # ------------------------------------------------------------------ sync

    def push_pending(self) -> int:
        """Upload saved labels to the bucket. Returns how many were pushed; stops at the first error."""
        pushed = 0
        for item in self.index.pending():
            try:
                gen = self.store.write(
                    f"{item.dataset}/labeling/labels/{item.id}.json",
                    item.data.encode("utf-8"),
                    "application/json",
                )
            except Exception as e:
                self.last_sync_error = f"{type(e).__name__}: {e}"
                log.warning("Label sync failed: %s", self.last_sync_error)
                return pushed
            self.index.mark_pushed(item, gen)
            pushed += 1
        self.last_sync_error = None
        return pushed
