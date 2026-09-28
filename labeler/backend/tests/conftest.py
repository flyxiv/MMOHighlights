import os

os.environ["LABELER_RUN_WORKERS"] = "false"

import hashlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from io import BytesIO  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import LocalStore  # noqa: E402

VALIDATOR = Path(__file__).parent / "vendor" / "validate_release.py"


def png(w: int = 64, h: int = 36, color=(40, 30, 80)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def sid(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def validate(bucket: LocalStore, name: str) -> str:
    """Run data-merge's validate_release.py on a dataset; returns its output, fails the test on errors."""
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), str(bucket.root / "datasets" / name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


@pytest.fixture
def bucket(tmp_path: Path) -> LocalStore:
    return LocalStore(tmp_path / "bucket")


@pytest.fixture
def make_client(tmp_path: Path, bucket: LocalStore):
    """A client over the shared bucket. Each call can use a fresh cache, like another machine."""

    def make(cache: str = "cache") -> TestClient:
        settings = Settings(storage=str(bucket.root), cache_dir=tmp_path / cache, run_workers=False)
        return TestClient(create_app(settings, store=bucket))

    return make


@pytest.fixture
def client(make_client) -> Iterator[TestClient]:
    with make_client() as c:
        yield c


@pytest.fixture
def frames(tmp_path: Path) -> Path:
    """3 distinct frames (one in a subfolder, one with a Korean name), a duplicate, and a non-image."""
    d = tmp_path / "frames"
    (d / "pull2").mkdir(parents=True)
    (d / "f001.png").write_bytes(png())
    (d / "풀 2.png").write_bytes(png(color=(90, 20, 20)))
    (d / "pull2" / "f003.png").write_bytes(png(1920, 1080))
    (d / "pull2" / "copy_of_f001.png").write_bytes(png())
    (d / "notes.txt").write_text("not an image")
    return d


NEW_DATASET = {
    "name": "raid_ui",
    "title": "FFXIV raid UI",
    "project": "MMOHighlights",
    "tasks": {"fight_state": {"type": "class"}, "ui": {"type": "bbox"}, "tags": {"type": "multilabel"}},
    "classes": {
        "fight_state": ["pre_pull", "in_combat", "wipe"],
        "ui": ["boss_hp_bar", "cast_bar"],
        "tags": ["blurry", "ui_hidden"],
    },
}

BASE_IMAGES = {"a": png(color=(1, 2, 3)), "b": png(color=(4, 5, 6)), "c": png(100, 50, color=(7, 8, 9))}


@pytest.fixture
def released(bucket: LocalStore) -> dict[str, str]:
    """A dataset built by data-merge's tools: dataset.json + releases/v1 with 3 samples."""
    root = bucket.root / "datasets" / "ffxiv_frames"
    ids = {}
    lines = []
    for key, data in BASE_IMAGES.items():
        i = sid(data)
        ids[key] = i
        (root / "releases/v1/data/image").mkdir(parents=True, exist_ok=True)
        (root / f"releases/v1/data/image/{i}.png").write_bytes(data)
        lines.append(
            {"id": i, "split": "train", "files": {"image": f"releases/v1/data/image/{i}.png"}, "labels": {}}
        )
    lines[0]["labels"] = {
        "phase": {"type": "class", "value": "p1"},
        "caption": {"type": "text", "value": "boss at 60%"},
    }
    lines[0]["meta"] = {"width": 64, "height": 36, "source": "vod/0412"}
    lines[2]["split"] = "unsplit"
    (root / "releases/v1/manifest.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    (root / "releases/v1/classes.json").write_text(json.dumps({"phase": ["p1", "p2"]}))
    (root / "releases/v1/splits").mkdir()
    (root / "releases/v1/splits/train.txt").write_text(f"{ids['a']}\n{ids['b']}\n")
    (root / "releases/v1/splits/val.txt").write_text("")
    (root / "releases/v1/splits/test.txt").write_text("")
    card = {
        "name": "ffxiv_frames",
        "title": "FFXIV frames",
        "modality": ["image"],
        "tasks": {"phase": {"type": "class"}, "caption": {"type": "text"}},
        "license": "private",
        "created": "2026-09-26",
        "latest": "v1",
        "versions": {"v1": {"created": "2026-09-26", "samples": 3}},
    }
    (root / "dataset.json").write_text(json.dumps(card))
    validate(bucket, "ffxiv_frames")
    return ids
