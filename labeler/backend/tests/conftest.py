import os

os.environ["LABELER_RUN_WORKERS"] = "false"

from collections.abc import Iterator  # noqa: E402
from io import BytesIO  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import LocalStore  # noqa: E402


def png(w: int = 64, h: int = 36, color=(40, 30, 80)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


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
    """A folder with 3 frames (one in a subfolder) and a non-image."""
    d = tmp_path / "frames"
    (d / "pull2").mkdir(parents=True)
    (d / "f001.png").write_bytes(png())
    (d / "f002.png").write_bytes(png(color=(90, 20, 20)))
    (d / "pull2" / "f003.png").write_bytes(png(1920, 1080))
    (d / "notes.txt").write_text("not an image")
    return d


PROJECT = {
    "name": "FFXIV raid UI",
    "tasks": ["classification", "detection"],
    "classes": [{"name": "boss_hp_bar"}, {"name": "cast_bar", "color": "orange"}],
    "groups": [{"name": "fight_state", "options": ["Pre-pull", "In combat", "Wipe"]}],
}
