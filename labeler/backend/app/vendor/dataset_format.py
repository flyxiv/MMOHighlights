# Vendored verbatim from RaidDesigner, branch flyxiv/data-merge, datasets/tools/dataset_format.py
# (uncommitted, copied 2026-09-27, sha256 8c56921ad90e4e54). Don't edit here: change it there and
# re-run labeler/backend/scripts/vendor_dataset_format.py.
#!/usr/bin/env python3
"""Single-file, stdlib-only implementation of the ai_datasets_jyn dataset format.

Source of truth: datasets/STRUCTURE.md in the RaidDesigner repo. This module is meant
to be vendored verbatim by other programs (the MMOHighlights labeler backend), so it
must stay one file with no imports outside the standard library. The CLIs next to it
(validate_release.py, cut_release.py, build_manifest.py) are thin wrappers.

Public API
----------
Validation (Report collects errors/warnings; nothing raises):
    check_card(card, rep, folder_name=None) -> declared_tasks
    check_classes(classes, rep, where="classes.json") -> classes
    validate_manifest(lines, rep, root=None) -> {"ids", "split_of", "n", "used_classes", "label_types_seen"}
    check_vocab(used_classes, label_types_seen, classes, declared_tasks, rep)
    check_labels(labels, where, rep, used_classes, label_types_seen, root=None)

Split and stats:
    assign_split(dataset_name, sample_id, ratio=(0.8, 0.1, 0.1)) -> "train" | "val" | "test"
    compute_stats(manifest, built) -> dict

Cutting a release from labeling/ (STRUCTURE.md 5a), pure, writes nothing:
    cut_release(card, base_manifest, base_classes, project, classes, label_files, *, today=None, notes="", root=None)
      -> {"version", "manifest", "classes", "splits", "stats", "card", "project", "errors", "warnings"}
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

FORMAT_VERSION = "2026-09-27"

LABEL_TYPES = {"class", "multilabel", "bbox", "polygon", "mask", "keypoints", "span", "scalar", "text", "ref"}
SPLITS = {"train", "val", "test", "unsplit"}
MANIFEST_KEYS = {"id", "split", "files", "labels", "meta"}
STATUSES = {"todo", "review", "done", "excluded"}
LABEL_FILE_KEYS = {"id", "status", "labels", "suggestions", "files", "meta", "updated_at"}
CARD_REQUIRED = ("name", "title", "modality", "tasks", "license", "created", "latest", "versions")
CARD_DRAFT_KEYS = (
    "name",
    "title",
    "description",
    "modality",
    "source",
    "license",
    "project",
    "tags",
    "split_ratio",
)
MODALITIES = {"image", "video", "audio", "3d", "text", "tabular"}
DEFAULT_RATIO = (0.8, 0.1, 0.1)
ID_RE = re.compile(r"^[a-z0-9_]{4,64}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")
VER_RE = re.compile(r"^v[0-9]+$")


# ------------------------------------------------------------------------------------------------
# validation
# ------------------------------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        if len(self.errors) < 200:
            self.errors.append(msg)
        elif len(self.errors) == 200:
            self.errors.append("... (more errors suppressed)")

    def warn(self, msg: str) -> None:
        if len(self.warnings) < 50:
            self.warnings.append(msg)


def is_relpath(p) -> bool:
    """Dataset-root-relative object path: no leading slash, no '..', no whitespace."""
    return (
        isinstance(p, str)
        and bool(p)
        and not p.startswith("/")
        and "../" not in p
        and not re.search(r"\s", p)
    )


def check_value(t: str, v, where: str, rep: Report) -> list[str]:
    """Check a label value against its type. Return the class names used inside it."""
    used: list[str] = []

    def item_list(required: tuple[str, ...]) -> list[dict]:
        if not isinstance(v, list):
            rep.err(f"{where}: {t} value must be a list")
            return []
        ok = []
        for i, it in enumerate(v):
            if not isinstance(it, dict) or any(k not in it for k in required):
                rep.err(f"{where}[{i}]: {t} item needs keys {required}")
                continue
            ok.append(it)
        return ok

    if t == "class":
        if not isinstance(v, str):
            rep.err(f"{where}: class value must be a string")
        else:
            used.append(v)
    elif t == "multilabel":
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            rep.err(f"{where}: multilabel value must be a list of strings")
        else:
            used.extend(v)
    elif t == "bbox":
        for it in item_list(("class", "xyxy")):
            b = it["xyxy"]
            if not (isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)):
                rep.err(f"{where}: xyxy must be 4 numbers")
            elif b[0] > b[2] or b[1] > b[3]:
                rep.err(f"{where}: xyxy must be x1<=x2, y1<=y2: {b}")
            used.append(it["class"])
    elif t == "polygon":
        for it in item_list(("class", "points")):
            pts = it["points"]
            if not (
                isinstance(pts, list)
                and len(pts) >= 3
                and all(isinstance(p, list) and len(p) == 2 for p in pts)
            ):
                rep.err(f"{where}: polygon points must be >=3 [x,y] pairs")
            used.append(it["class"])
    elif t == "mask":
        if not (isinstance(v, dict) and is_relpath(v.get("path"))):
            rep.err(f"{where}: mask value must be {{'path': <relpath>}}")
    elif t == "keypoints":
        for it in item_list(("class", "points")):
            pts = it["points"]
            if not (isinstance(pts, list) and all(isinstance(p, list) and 2 <= len(p) <= 3 for p in pts)):
                rep.err(f"{where}: keypoints must be [x,y] or [x,y,v] lists")
            used.append(it["class"])
    elif t == "span":
        for it in item_list(("class", "start", "end")):
            s, e = it["start"], it["end"]
            if not (isinstance(s, (int, float)) and isinstance(e, (int, float))):
                rep.err(f"{where}: span start/end must be numbers")
            elif e < s:
                rep.err(f"{where}: span end < start ({s} > {e})")
            used.append(it["class"])
    elif t == "scalar":
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            rep.err(f"{where}: scalar value must be a number")
    elif t == "text":
        if not isinstance(v, str):
            rep.err(f"{where}: text value must be a string")
    elif t == "ref":
        if not (isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v))):
            rep.err(f"{where}: ref value must be an id or list of ids")
    return used


def check_labels(
    labels,
    where: str,
    rep: Report,
    used_classes: dict[str, set[str]],
    label_types_seen: dict[str, set[str]],
    root: Path | None = None,
) -> None:
    """Check one sample's labels object (manifest format). Shared by manifests and labeling/ files."""
    if not isinstance(labels, dict):
        rep.err(f"{where}: labels must be an object")
        return
    for task, lab in labels.items():
        if not isinstance(lab, dict) or "type" not in lab or "value" not in lab:
            rep.err(f"{where}: labels.{task} must be {{type, value}}")
            continue
        t = lab["type"]
        if t not in LABEL_TYPES:
            rep.err(f"{where}: labels.{task} unknown type {t!r}")
            continue
        label_types_seen.setdefault(task, set()).add(t)
        for c in check_value(t, lab["value"], f"{where} labels.{task}", rep):
            used_classes.setdefault(task, set()).add(c)
        if t == "mask" and root is not None and isinstance(lab["value"], dict):
            mp = lab["value"].get("path")
            if is_relpath(mp) and not (root / mp).exists():
                rep.err(f"{where}: mask path not found: {mp}")


def validate_manifest(lines: Iterable[tuple[str, object]], rep: Report, root: Path | None = None) -> dict:
    """Validate manifest lines. `lines` yields (where, parsed_object_or_json_string).

    Pass `root` (a local dataset root) to also check that referenced files exist.
    Returns ids, split_of, n, used_classes, label_types_seen for check_vocab().
    """
    ids: set[str] = set()
    split_of: dict[str, str] = {}
    n = 0
    used_classes: dict[str, set[str]] = {}
    label_types_seen: dict[str, set[str]] = {}
    missing_files = 0
    for where, s in lines:
        n += 1
        if isinstance(s, str):
            try:
                s = json.loads(s)
            except json.JSONDecodeError as e:
                rep.err(f"{where}: invalid JSON: {e}")
                continue
        if not isinstance(s, dict):
            rep.err(f"{where}: line must be an object")
            continue
        for k in ("id", "split", "files", "labels"):
            if k not in s:
                rep.err(f"{where}: missing '{k}'")
        extra = set(s) - MANIFEST_KEYS
        if extra:
            rep.err(f"{where}: unknown top-level keys {sorted(extra)}")
        sid = s.get("id")
        if not isinstance(sid, str) or not ID_RE.match(sid):
            rep.err(f"{where}: bad id {sid!r}")
        elif sid in ids:
            rep.err(f"{where}: duplicate id {sid}")
        else:
            ids.add(sid)
        sp = s.get("split")
        if sp not in SPLITS:
            rep.err(f"{where}: split must be one of {sorted(SPLITS)}, got {sp!r}")
        elif isinstance(sid, str):
            split_of[sid] = sp
        files = s.get("files")
        if not isinstance(files, dict) or not files:
            rep.err(f"{where}: files must be a non-empty object")
        else:
            for role, p in files.items():
                paths = p if isinstance(p, list) else [p]
                for one in paths:
                    if not is_relpath(one):
                        rep.err(f"{where}: files.{role} bad path {one!r}")
                    elif root is not None and not (root / one).exists():
                        missing_files += 1
                        if missing_files <= 20:
                            rep.err(f"{where}: files.{role} not found: {one}")
        if "meta" in s and not isinstance(s["meta"], dict):
            rep.err(f"{where}: meta must be an object")
        check_labels(s.get("labels"), where, rep, used_classes, label_types_seen, root)
    if missing_files > 20:
        rep.err(f"... {missing_files} referenced files missing in total")
    return {
        "ids": ids,
        "split_of": split_of,
        "n": n,
        "used_classes": used_classes,
        "label_types_seen": label_types_seen,
    }


def check_vocab(
    used_classes: dict[str, set[str]],
    label_types_seen: dict[str, set[str]],
    classes: dict,
    declared_tasks: dict,
    rep: Report,
) -> None:
    """Class names must exist in classes.json; one type per task; tasks declared in dataset.json."""
    for task, names in used_classes.items():
        vocab = set(classes.get(task, []))
        if not vocab:
            rep.err(f"classes.json has no vocabulary for task '{task}' (used: {sorted(names)[:5]}...)")
        else:
            unknown = sorted(names - vocab)
            if unknown:
                rep.err(f"task '{task}' uses classes not in classes.json: {unknown[:10]}")
    for task, types in label_types_seen.items():
        if len(types) > 1:
            rep.err(f"task '{task}' mixes label types {sorted(types)}; one type per task")
        if task not in declared_tasks:
            rep.warn(f"task '{task}' is used in the manifest but not declared in dataset.json tasks")
        elif declared_tasks[task].get("type") not in types:
            rep.err(
                f"task '{task}' declared as {declared_tasks[task].get('type')} in dataset.json but manifest uses {sorted(types)}"
            )


def check_classes(classes, rep: Report, where: str = "classes.json") -> dict:
    if not isinstance(classes, dict) or not all(
        isinstance(v, list) and all(isinstance(c, str) for c in v) for v in classes.values()
    ):
        rep.err(f"{where} must map task -> list of class names")
        return {}
    for task, names in classes.items():
        if len(set(names)) != len(names):
            rep.err(f"{where}: task '{task}' has duplicate class names")
    return classes


def check_card(card: dict, rep: Report, folder_name: str | None = None) -> dict:
    """Check dataset.json. Returns the declared tasks."""
    for k in CARD_REQUIRED:
        if k not in card:
            rep.err(f"dataset.json: missing required key '{k}'")
    if card.get("name") and not NAME_RE.match(str(card["name"])):
        rep.err(f"dataset.json: name '{card['name']}' must be snake_case ascii")
    if folder_name and card.get("name") and card["name"] != folder_name:
        rep.warn(f"dataset.json name '{card['name']}' differs from folder name '{folder_name}'")
    if str(card.get("name", "")).endswith("_dataset"):
        rep.warn("dataset.json: drop the redundant '_dataset' suffix from the name")
    mod = card.get("modality")
    if mod is not None and not (isinstance(mod, list) and mod and set(mod) <= MODALITIES):
        rep.err(f"dataset.json: modality must be a non-empty list from {sorted(MODALITIES)}")
    if "latest" in card and not VER_RE.match(str(card["latest"])):
        rep.err(f"dataset.json: latest must look like vN, got {card['latest']!r}")
    for v in card.get("versions", {}) or {}:
        if not VER_RE.match(v):
            rep.err(f"dataset.json: version key '{v}' must look like vN")
    ratio = card.get("split_ratio")
    if ratio is not None and not (isinstance(ratio, list) and len(ratio) == 3 and abs(sum(ratio) - 1) < 1e-6):
        rep.err("dataset.json: split_ratio must be three numbers summing to 1")
    declared = card.get("tasks", {}) if isinstance(card.get("tasks"), dict) else {}
    for task, spec in declared.items():
        if not isinstance(spec, dict) or spec.get("type") not in LABEL_TYPES:
            rep.err(f"dataset.json: task '{task}' must declare a type in {sorted(LABEL_TYPES)}")
    return declared


# ------------------------------------------------------------------------------------------------
# split, stats, helpers
# ------------------------------------------------------------------------------------------------


def assign_split(dataset_name: str, sample_id: str, ratio=DEFAULT_RATIO) -> str:
    """The one split function every tool must use. Seeded by dataset name, so stable across versions."""
    x = int(hashlib.sha256(f"{dataset_name}:{sample_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    train, val, _ = ratio
    if x < train:
        return "train"
    if x < train + val:
        return "val"
    return "test"


def sample_id_for_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def next_version(card: dict) -> str:
    nums = [int(v[1:]) for v in (card.get("versions") or {}) if VER_RE.match(v)]
    return f"v{max(nums) + 1}" if nums else "v1"


def manifest_to_jsonl(manifest: list[dict]) -> str:
    return "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in manifest)


def splits_of(manifest: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in ("train", "val", "test")}
    for s in manifest:
        if s.get("split") in out:
            out[s["split"]].append(s["id"])
    for k in out:
        out[k].sort()
    return out


def compute_stats(manifest: list[dict], built: str) -> dict:
    by_split = Counter(s.get("split") for s in manifest)
    per_class: dict[str, Counter] = defaultdict(Counter)  # sample counts for class / multilabel
    instances: dict[str, Counter] = defaultdict(
        Counter
    )  # instance counts for bbox / polygon / keypoints / span
    labeled: Counter = Counter()
    for s in manifest:
        for task, lab in (s.get("labels") or {}).items():
            labeled[task] += 1
            t, v = lab.get("type"), lab.get("value")
            if t == "class" and isinstance(v, str):
                per_class[task][f"{v}/{s.get('split')}"] += 1
            elif t == "multilabel" and isinstance(v, list):
                for c in v:
                    per_class[task][f"{c}/{s.get('split')}"] += 1
            elif t in {"bbox", "polygon", "keypoints", "span"} and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict) and "class" in it:
                        instances[task][it["class"]] += 1
    return {
        "samples": len(manifest),
        "splits": dict(sorted(by_split.items())),
        "labeled": dict(sorted(labeled.items())),
        "reviewed": sum(1 for s in manifest if (s.get("meta") or {}).get("reviewed") is True),
        "classes": {t: dict(sorted(c.items())) for t, c in sorted(per_class.items())},
        "instances": {t: dict(sorted(c.items())) for t, c in sorted(instances.items())},
        "built": built,
    }


def _clone(o):
    return json.loads(json.dumps(o))


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------------------------------------
# cut a release from labeling/
# ------------------------------------------------------------------------------------------------


def cut_release(
    card: dict | None,
    base_manifest: list[dict] | None,
    base_classes: dict | None,
    project: dict,
    classes: dict | None,
    label_files: list[dict],
    *,
    today: str | None = None,
    notes: str = "",
    root: Path | None = None,
) -> dict:
    """Compose the next release from the base release plus labeling/. Pure: writes nothing.

    card           dataset.json, or None for a dataset that has no release yet; then the card
                   is built from project["card"] (name, title, description, modality, source,
                   license, project, tags, split_ratio)
    base_manifest  lines of releases/<base_release>/manifest.jsonl (None/[] when base_release is null)
    base_classes   releases/<base_release>/classes.json
    project        labeling/project.json  {"base_release": "vN" | None, "tasks": {task: {"type": ...}}, "card"?: {...}}
    classes        labeling/classes.json (None -> base_classes)
    label_files    contents of labeling/labels/*.json
    today          ISO date for versions.<new>.created (default: today)
    root           optional local dataset root; when given, referenced files are checked to exist

    Returns {"version", "manifest", "classes", "splits", "stats", "card", "project", "errors", "warnings"}.
    If "errors" is non-empty the other outputs are empty and nothing must be written.
    """
    rep = Report()
    today = today or dt.date.today().isoformat()
    base_manifest = base_manifest or []
    base_classes = base_classes or {}

    def fail() -> dict:
        return {
            "version": "",
            "manifest": [],
            "classes": {},
            "splits": {},
            "stats": {},
            "card": {},
            "project": {},
            "errors": rep.errors,
            "warnings": rep.warnings,
        }

    if not isinstance(project, dict):
        rep.err("project.json must be an object")
        return fail()
    project = _clone(project)

    # --- card ------------------------------------------------------------------------------
    if card is None:
        draft = project.get("card")
        if not isinstance(draft, dict):
            rep.err("no dataset.json and labeling/project.json has no 'card' draft")
            return fail()
        card = {k: _clone(draft[k]) for k in CARD_DRAFT_KEYS if k in draft}
        card.setdefault("title", str(card.get("name", "")).replace("_", " "))
        card.setdefault("modality", ["image"])
        card.setdefault("license", "private")
        card.update({"tasks": {}, "created": today, "latest": "v0", "versions": {}})
        if project.get("base_release") is not None:
            rep.err("project.json: base_release must be null when there is no dataset.json yet")
        declared_tasks: dict = {}
        card_probe = _clone(card)
        card_probe["latest"] = "v1"
        check_card(card_probe, rep)
    else:
        card = _clone(card)
        declared_tasks = check_card(card, rep)
    if not card.get("name"):
        rep.err("dataset.json needs a name")
        return fail()
    name = card["name"]
    ratio = tuple(card.get("split_ratio") or DEFAULT_RATIO)

    base_version = project.get("base_release")
    if base_version is not None:
        if not VER_RE.match(str(base_version)):
            rep.err(f"project.json: base_release must be vN or null, got {base_version!r}")
        elif base_version not in (card.get("versions") or {}):
            rep.err(f"project.json: base_release {base_version} is not in dataset.json versions")
    elif base_manifest:
        rep.err("project.json base_release is null but a base manifest was supplied")

    # --- tasks and classes ---------------------------------------------------------------
    project_tasks = project.get("tasks") or {}
    if not isinstance(project_tasks, dict):
        rep.err("project.json: tasks must be an object")
        project_tasks = {}
    for task, spec in project_tasks.items():
        t = spec.get("type") if isinstance(spec, dict) else None
        if t not in LABEL_TYPES:
            rep.err(f"project.json: task '{task}' must declare a type in {sorted(LABEL_TYPES)}")
        elif task in declared_tasks and declared_tasks[task].get("type") != t:
            rep.err(
                f"project.json: task '{task}' is {t} but dataset.json declares {declared_tasks[task].get('type')}"
            )

    classes = check_classes(
        _clone(classes if classes is not None else base_classes), rep, "labeling/classes.json"
    )
    for task, base_names in base_classes.items():
        new_names = classes.get(task)
        if new_names is None:
            rep.err(f"labeling/classes.json dropped task '{task}' that exists in the base release")
        elif new_names[: len(base_names)] != list(base_names):
            rep.err(
                f"labeling/classes.json: task '{task}' must start with the base vocabulary in the same order (append only)"
            )

    # --- label files ----------------------------------------------------------------------
    by_id: dict[str, dict] = {}
    for i, lf in enumerate(label_files or []):
        if not isinstance(lf, dict):
            rep.err(f"label file #{i}: must be an object")
            continue
        sid = lf.get("id")
        where = f"labels/{sid}.json"
        if not isinstance(sid, str) or not ID_RE.match(sid):
            rep.err(f"label file #{i}: bad id {sid!r}")
            continue
        if sid in by_id:
            rep.err(f"{where}: duplicate label file for id {sid}")
            continue
        extra = set(lf) - LABEL_FILE_KEYS
        if extra:
            rep.warn(f"{where}: unknown keys {sorted(extra)} ignored")
        if lf.get("status") not in STATUSES:
            rep.err(f"{where}: status must be one of {sorted(STATUSES)}, got {lf.get('status')!r}")
        if "labels" in lf and not isinstance(lf["labels"], dict):
            rep.err(f"{where}: labels must be an object")
        if "meta" in lf and not isinstance(lf["meta"], dict):
            rep.err(f"{where}: meta must be an object")
        by_id[sid] = lf

    base_ids = {s.get("id") for s in base_manifest if isinstance(s, dict)}
    for sid, lf in by_id.items():
        if (
            sid not in base_ids
            and lf.get("status") != "excluded"
            and not (isinstance(lf.get("files"), dict) and lf["files"])
        ):
            rep.err(f"labels/{sid}.json: sample is not in the base release, so 'files' is required")
    if rep.errors:
        return fail()

    # --- compose --------------------------------------------------------------------------
    manifest: list[dict] = []
    seen: set[str] = set()
    dropped = applied = 0

    def finish_sample(s: dict, lf: dict | None, is_new: bool) -> dict | None:
        nonlocal dropped, applied
        if lf is not None:
            if lf["status"] == "excluded":
                dropped += 1
                return None
            s["meta"] = {**(s.get("meta") or {}), **_clone(lf.get("meta") or {})}
            if lf["status"] == "done":
                s["labels"] = _clone(lf.get("labels") or {})
                s["meta"]["reviewed"] = True
                if lf.get("updated_at"):
                    s["meta"]["reviewed_at"] = lf["updated_at"]
                applied += 1
            elif is_new:
                s["labels"] = {}
        if s.get("split") in (None, "unsplit"):
            s["split"] = assign_split(name, s["id"], ratio)
        return {k: s[k] for k in ("id", "split", "files", "labels", "meta") if k in s}

    for base in base_manifest:
        s = _clone(base)
        sid = s.get("id")
        if not isinstance(sid, str) or sid in seen:
            continue
        seen.add(sid)
        out = finish_sample(s, by_id.get(sid), is_new=False)
        if out is not None:
            manifest.append(out)
    for sid in sorted(set(by_id) - base_ids):
        lf = by_id[sid]
        if lf["status"] == "excluded":
            dropped += 1
            continue
        s = {"id": sid, "split": "unsplit", "files": _clone(lf["files"]), "labels": {}, "meta": {}}
        out = finish_sample(s, lf, is_new=True)
        if out is not None:
            manifest.append(out)

    # --- validate the composed release with the shared rules ------------------------------
    version = next_version(card)
    card.setdefault("tasks", {})
    for task, spec in project_tasks.items():
        card["tasks"].setdefault(task, {"type": spec["type"]})
    check = validate_manifest(
        ((f"{version} manifest line {i} (id {s.get('id')})", s) for i, s in enumerate(manifest, 1)),
        rep,
        root=root,
    )
    for task, types in check["label_types_seen"].items():
        if task not in card["tasks"] and len(types) == 1:
            t = next(iter(types))
            card["tasks"][task] = {"type": t}
            rep.warn(f"task '{task}' was not declared; added to dataset.json as {t}")
    check_vocab(check["used_classes"], check["label_types_seen"], classes, card["tasks"], rep)
    if rep.errors:
        return fail()

    # --- outputs --------------------------------------------------------------------------
    stats = compute_stats(manifest, today)
    stats["from_labeling"] = {"applied_done": applied, "excluded": dropped, "label_files": len(by_id)}
    card["versions"][version] = {
        "created": today,
        "samples": len(manifest),
        "notes": notes or f"cut from labeling/ on top of {base_version or 'nothing'}",
    }
    card["latest"] = version
    project["base_release"] = version
    project["updated_at"] = _utc_now()
    return {
        "version": version,
        "manifest": manifest,
        "classes": classes,
        "splits": splits_of(manifest),
        "stats": stats,
        "card": card,
        "project": project,
        "errors": [],
        "warnings": rep.warnings,
    }
