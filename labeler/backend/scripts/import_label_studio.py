"""Prepare a uniform dataset from the copied Label Studio export, then optionally upload it.

Run with the backend environment. Preparation is local; --upload explicitly writes to GCS.
Existing local datasets are refused. Existing remote objects must match exactly and are
never overwritten. dataset.json is published last, after every referenced object verifies.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.vendor.dataset_format import cut_release  # noqa: E402


def digest(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare(source: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError(f"Output already exists; refusing to overwrite: {output}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{1,63}", output.name):
        raise ValueError("Output directory name must be a valid dataset name")
    tasks = json.loads((source / "annotations.json").read_text(encoding="utf-8"))
    provenance = json.loads((source / "COPY_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in provenance["frames"]}
    if digest(source / "source-export.json") != provenance["original_export_sha256"]:
        raise ValueError("Original annotation export has changed")
    if len(tasks) != provenance["frame_count"]:
        raise ValueError("Task count does not match the copy manifest")

    labels, vocabulary, inputs = [], [], []
    seen_ids, seen_paths = set(), set()
    now = datetime.now(UTC).isoformat()
    for task in tasks:
        annotations = task.get("annotations", [])
        if len(annotations) != 1 or annotations[0].get("was_cancelled"):
            raise ValueError(f"Task {task['id']}: expected one completed, non-cancelled annotation")
        annotation = annotations[0]
        choices = []
        for result in annotation["result"]:
            if result["type"] != "choices" or result["from_name"] != "tags":
                raise ValueError(f"Task {task['id']}: unsupported annotation type or field")
            values = result["value"]["choices"]
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"Task {task['id']}: malformed choices")
            for value in values:
                if value not in choices:
                    choices.append(value)
                if value not in vocabulary:
                    vocabulary.append(value)
        relative = task["data"]["image"]
        frame = (source / relative).resolve()
        if not frame.is_relative_to(source.resolve()) or relative not in expected:
            raise ValueError(f"Unrecognized image path: {relative}")
        info = expected[relative]
        if info["task_id"] != task["id"] or digest(frame) != info["sha256"]:
            raise ValueError(f"Frame does not match the verified copy: {relative}")
        sid = info["sha256"][:16]
        if sid in seen_ids or relative in seen_paths:
            raise ValueError("Duplicate content or image references require manual reconciliation")
        seen_ids.add(sid)
        seen_paths.add(relative)
        image_path = f"raw/label_studio/{sid}.png"
        inputs.append((frame, image_path))
        labels.append(
            {
                "id": sid,
                "status": "done",
                "files": {"image": image_path},
                "labels": {"tags": {"type": "multilabel", "value": choices}},
                "meta": {
                    "original_path": relative,
                    "width": info["width"],
                    "height": info["height"],
                    "label_studio_task_id": task["id"],
                    "label_studio_annotation_id": annotation["id"],
                    "annotation_source": "archive/label_studio/source-export.json",
                },
                "updated_at": annotation["updated_at"],
            }
        )
    if seen_paths != set(expected):
        raise ValueError("Copy manifest contains images missing from the annotations")
    project = {
        "base_release": None,
        "tool": "labeler",
        "updated_at": now,
        "tasks": {"tags": {"type": "multilabel"}},
        "card": {
            "name": output.name,
            "title": "FFXIV combat frames",
            "description": "456 manually annotated FFXIV frames imported from Label Studio project 3.",
            "modality": ["image"],
            "license": "private",
            "project": "MMOHighlights",
            "tags": ["ffxiv", "combat", "label-studio"],
        },
    }
    result = cut_release(
        None,
        None,
        None,
        project,
        {"tags": vocabulary},
        labels,
        notes="Imported completed Label Studio annotations, preserving empty-tag samples.",
    )
    if result["errors"]:
        raise ValueError(result["errors"])
    counts = dict(Counter(v for label in labels for v in label["labels"]["tags"]["value"]))
    if counts != provenance["label_counts"]:
        raise ValueError("Converted label counts differ from the source")

    # Preflight is complete before writing. Hard links avoid another 1.89 GB local copy;
    # these raw image bytes are immutable in the labeler.
    for frame, relative in inputs:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(frame, target)
        except OSError:
            shutil.copy2(frame, target)
    for label in labels:
        write_json(output / "labeling/labels" / f"{label['id']}.json", label)
    write_json(output / "labeling/project.json", result["project"])
    write_json(output / "labeling/classes.json", result["classes"])
    release = output / "releases" / result["version"]
    release.mkdir(parents=True)
    (release / "manifest.jsonl").write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in result["manifest"]),
        encoding="utf-8",
    )
    write_json(release / "classes.json", result["classes"])
    write_json(release / "stats.json", result["stats"])
    (release / "splits").mkdir()
    for split in ("train", "val", "test"):
        (release / "splits" / f"{split}.txt").write_text(
            "".join(sid + "\n" for sid in result["splits"].get(split, [])), encoding="utf-8"
        )
    archive = output / "archive/label_studio"
    archive.mkdir(parents=True)
    for name in ("source-export.json", "annotations.json", "COPY_MANIFEST.json"):
        shutil.copy2(source / name, archive / name)
    write_json(output / "dataset.json", result["card"])
    summary = {
        "dataset": output.name,
        "samples": len(labels),
        "labels": counts,
        "empty_tag_samples": sum(not item["labels"]["tags"]["value"] for item in labels),
        "version": result["version"],
        "warnings": result["warnings"],
    }
    print(json.dumps(summary), flush=True)
    return summary


def upload(root: Path, bucket_name: str) -> dict:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    prefix = f"datasets/{root.name}/"
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not (root / "dataset.json").is_file():
        raise ValueError("Prepare and validate a release before uploading")
    # Read only this dataset prefix. Existing objects are reusable only when bytes match.
    existing = {b.name: b for b in client.list_blobs(bucket, prefix=prefix)}
    metadata = {}
    for path in files:
        name = prefix + path.relative_to(root).as_posix()
        md5 = base64.b64encode(bytes.fromhex(digest(path, "md5"))).decode("ascii")
        metadata[name] = (path, md5)
        if name in existing and (
            existing[name].md5_hash != md5 or existing[name].size != path.stat().st_size
        ):
            raise ValueError(f"Remote object differs; refusing to overwrite: gs://{bucket_name}/{name}")
    if set(existing) - set(metadata):
        raise ValueError("Target prefix contains unrelated objects; refusing to mix datasets")

    def put(name: str) -> bool:
        if name in existing:
            return False
        path, _ = metadata[name]
        blob = bucket.blob(name)
        blob.upload_from_filename(
            str(path),
            if_generation_match=0,
            checksum="crc32c",
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            timeout=180,
        )
        return True

    final = [prefix + "labeling/project.json", prefix + "dataset.json"]
    first = [name for name in metadata if name not in final]
    uploaded = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        for count, changed in enumerate(pool.map(put, first), 1):
            uploaded += changed
            if count % 100 == 0:
                print(f"Uploaded/checked {count}/{len(metadata)} objects", flush=True)
    # Confirm bytes in GCS before making the dataset discoverable.
    remote = {b.name: b for b in client.list_blobs(bucket, prefix=prefix)}
    for name in first:
        path, md5 = metadata[name]
        if name not in remote or remote[name].md5_hash != md5 or remote[name].size != path.stat().st_size:
            raise ValueError(f"Remote checksum or size mismatch: {name}")
    for name in final:
        uploaded += put(name)
    remote = {b.name: b for b in client.list_blobs(bucket, prefix=prefix)}
    for name, (path, md5) in metadata.items():
        if name not in remote or remote[name].md5_hash != md5 or remote[name].size != path.stat().st_size:
            raise ValueError(f"Final remote verification failed: {name}")
    summary = {
        "uri": f"gs://{bucket_name}/{prefix}",
        "objects": len(metadata),
        "uploaded": uploaded,
        "reused": len(metadata) - uploaded,
        "bytes": sum(path.stat().st_size for path, _ in metadata.values()),
        "verified": "All remote object sizes and MD5 hashes match; upload CRC32C checked.",
    }
    print(json.dumps(summary), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Portable dataset folder")
    parser.add_argument("output", type=Path, help="New uniform dataset folder")
    parser.add_argument("--upload", metavar="BUCKET", help="Upload an already prepared dataset")
    parser.add_argument("--receipt", type=Path, help="Write the result outside the dataset root")
    args = parser.parse_args()
    result = upload(args.output, args.upload) if args.upload else prepare(args.source, args.output)
    if args.receipt:
        write_json(args.receipt, result)


if __name__ == "__main__":
    main()
