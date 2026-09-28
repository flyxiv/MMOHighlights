"""Copy the uniform dataset format rules from RaidDesigner (branch flyxiv/data-merge) into this backend.

    uv run python scripts/vendor_dataset_format.py [path/to/RaidDesigner/datasets/tools]

dataset_format.py is the single implementation of the spec (validation, splits, cut_release). It goes
to app/vendor/ for the backend and, with the validate_release.py CLI, to tests/vendor/ so the tests
check releases with data-merge's own validator.
"""

import hashlib
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEFAULT = Path.home() / "orca/workspaces/RaidDesigner/data-merge/datasets/tools"


def header(src: Path) -> str:
    try:
        commit = subprocess.run(
            ["git", "-C", str(src), "log", "-1", "--format=%h", "--", src.name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(src), "status", "--porcelain", "--", src.name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "", "?"
    state = f"commit {commit}" if commit and not dirty else "uncommitted"
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    return (
        f"# Vendored verbatim from RaidDesigner, branch flyxiv/data-merge, datasets/tools/{src.name}\n"
        f"# ({state}, copied {date.today()}, sha256 {digest}). Don't edit here: change it there and\n"
        f"# re-run labeler/backend/scripts/vendor_dataset_format.py.\n"
    )


def main() -> None:
    tools = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    for name, targets in {
        "dataset_format.py": [HERE / "app/vendor", HERE / "tests/vendor"],
        "validate_release.py": [HERE / "tests/vendor"],
    }.items():
        src = tools / name
        text = header(src) + src.read_text(encoding="utf-8")
        for t in targets:
            t.mkdir(parents=True, exist_ok=True)
            (t / "__init__.py").touch()
            (t / name).write_text(text, encoding="utf-8", newline="\n")
            print(f"{src} -> {t / name}")


if __name__ == "__main__":
    main()
