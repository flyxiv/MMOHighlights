"""Blob storage. GCS in production; a local folder for development without credentials."""

import asyncio
import shutil
from pathlib import Path
from typing import Protocol

from app.config import Settings


class Storage(Protocol):
    async def upload_file(self, local: Path, name: str, content_type: str) -> None: ...

    async def upload_text(self, data: str, name: str, content_type: str) -> None: ...


class GcsStorage:
    def __init__(self, bucket: str, project: str = ""):
        self._bucket_name = bucket
        self._project = project
        self._bucket_obj = None

    @property
    def _bucket(self):
        # Created on first upload, so the service starts even before credentials exist; uploads
        # fail and retry with backoff until they do.
        if self._bucket_obj is None:
            import google.auth
            from google.cloud import storage

            credentials, default_project = google.auth.default()
            # Uploading to an existing bucket doesn't use the project, but the client insists on one;
            # user logins (gcloud auth application-default login) usually don't carry a default.
            project = self._project or default_project or "unset"
            self._bucket_obj = storage.Client(credentials=credentials, project=project).bucket(
                self._bucket_name
            )
        return self._bucket_obj

    async def upload_file(self, local: Path, name: str, content_type: str) -> None:
        def run() -> None:
            blob = self._bucket.blob(name)
            # Resumable for large files; CRC32C is verified by the client after upload.
            blob.upload_from_filename(str(local), content_type=content_type, checksum="crc32c", timeout=600)

        await asyncio.to_thread(run)

    async def upload_text(self, data: str, name: str, content_type: str) -> None:
        def run() -> None:
            blob = self._bucket.blob(name)
            blob.cache_control = "no-cache"
            blob.upload_from_string(data.encode("utf-8"), content_type=content_type)

        await asyncio.to_thread(run)


class LocalStorage:
    def __init__(self, root: Path):
        self._root = root

    async def upload_file(self, local: Path, name: str, content_type: str) -> None:
        dest = self._root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, local, dest)

    async def upload_text(self, data: str, name: str, content_type: str) -> None:
        dest = self._root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(dest.write_text, data, "utf-8")


def make_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir / settings.gcs_bucket)
    return GcsStorage(settings.gcs_bucket, settings.gcs_project)
