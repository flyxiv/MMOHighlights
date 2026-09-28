from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="LABELER_", extra="ignore"
    )

    # Where projects live: "gs://bucket[/prefix]" or a local folder (for development and tests).
    # Each project is a folder here holding project.json, manifest.json, images/, annotations/, exports/.
    storage: str = "gs://ai_datasets_jyn"

    # Local copies of images and thumbnails, plus a SQLite index of every label. The bucket is the
    # source of truth; the index makes filtering and saving instant and queues writes to the bucket.
    cache_dir: Path = Path("./.cache")

    thumb_width: int = 320
    # Parallel transfers when importing images or pulling a project's labels from the bucket.
    transfer_workers: int = 16
    # How often the sync worker pushes saved labels to the bucket.
    sync_interval_s: float = 1.0

    # Disable the background sync worker; tests push explicitly.
    run_workers: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3100"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
