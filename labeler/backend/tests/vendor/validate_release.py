# Vendored verbatim from RaidDesigner, branch flyxiv/data-merge, datasets/tools/validate_release.py
# (uncommitted, copied 2026-09-27, sha256 a40892108b364834). Don't edit here: change it there and
# re-run labeler/backend/scripts/vendor_dataset_format.py.
#!/usr/bin/env python3
"""Validate a local dataset root against the uniform layout (datasets/STRUCTURE.md).

  python validate_release.py <dataset_root> [--version vN] [--no-files]

Checks: dataset.json shape, manifest lines, unique ids, split lists consistent with
the manifest, referenced files exist (relative to the dataset root), label types in
the vocabulary, class values present in classes.json, tasks declared in dataset.json.
Exit code 1 if any error. Thin CLI over dataset_format.py, which holds the rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataset_format as df  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path, help="dataset root (folder containing dataset.json and releases/)")
    ap.add_argument("--version", help="release to check (default: dataset.json 'latest')")
    ap.add_argument("--no-files", action="store_true", help="skip checking that referenced files exist")
    args = ap.parse_args()
    root: Path = args.root.expanduser().resolve()
    rep = df.Report()

    card_path = root / "dataset.json"
    card: dict = {}
    if not card_path.exists():
        rep.err("dataset.json missing at dataset root")
    else:
        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            rep.err(f"dataset.json: invalid JSON: {e}")
    declared_tasks = df.check_card(card, rep, root.name) if card else {}

    version = args.version or card.get("latest")
    if not version or not df.VER_RE.match(str(version)):
        rep.err(f"no valid release version (got {version!r}); pass --version vN")
        return finish(rep)
    if card.get("versions") and version not in card["versions"]:
        rep.err(f"dataset.json: versions has no entry for {version}")

    release = root / "releases" / version
    manifest_path = release / "manifest.jsonl"
    if not manifest_path.exists():
        rep.err(f"missing {manifest_path.relative_to(root)}")
        return finish(rep)

    classes: dict = {}
    classes_path = release / "classes.json"
    if classes_path.exists():
        try:
            classes = df.check_classes(json.loads(classes_path.read_text(encoding="utf-8")), rep)
        except json.JSONDecodeError as e:
            rep.err(f"classes.json: invalid JSON: {e}")
    else:
        rep.warn("classes.json missing (fine only for fully unlabeled releases)")

    with manifest_path.open(encoding="utf-8") as f:
        lines = ((f"manifest.jsonl:{i}", line) for i, line in enumerate(f, 1) if line.strip())
        res = df.validate_manifest(lines, rep, root=None if args.no_files else root)
    df.check_vocab(res["used_classes"], res["label_types_seen"], classes, declared_tasks, rep)
    ids, split_of, n = res["ids"], res["split_of"], res["n"]

    splits_dir = release / "splits"
    if not splits_dir.is_dir():
        rep.err("splits/ directory missing")
    else:
        listed: dict[str, str] = {}
        for name in ("train", "val", "test"):
            p = splits_dir / f"{name}.txt"
            if not p.exists():
                rep.warn(f"splits/{name}.txt missing")
                continue
            for i in p.read_text(encoding="utf-8").split():
                if i in listed:
                    rep.err(f"id {i} appears in both splits/{listed[i]}.txt and splits/{name}.txt")
                listed[i] = name
                if i not in ids:
                    rep.err(f"splits/{name}.txt lists unknown id {i}")
        for sid, sp in split_of.items():
            if sp == "unsplit":
                if sid in listed:
                    rep.err(f"id {sid} is 'unsplit' in manifest but listed in splits/{listed[sid]}.txt")
            elif listed.get(sid) != sp:
                rep.err(
                    f"id {sid} is '{sp}' in manifest but {'missing from splits/' if sid not in listed else 'in splits/' + listed[sid] + '.txt'}"
                )
                if len(rep.errors) >= 200:
                    break

    if card.get("versions", {}).get(version, {}).get("samples") not in (None, n):
        rep.warn(
            f"dataset.json versions.{version}.samples = {card['versions'][version]['samples']} but manifest has {n}"
        )

    print(
        f"{root.name} {version}: {n} samples, {len(ids)} unique ids, splits {dict(Counter(split_of.values()))}"
    )
    return finish(rep)


def finish(rep: df.Report) -> int:
    for w in rep.warnings:
        print(f"WARN  {w}")
    for e in rep.errors:
        print(f"ERROR {e}")
    if rep.errors:
        print(f"FAILED: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
        return 1
    print(f"OK ({len(rep.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
