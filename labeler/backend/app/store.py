"""Blob storage rooted at a folder: a GCS bucket prefix in production, a local directory otherwise.

Names are always "/"-separated and relative to the root.
"""

import os
import shutil
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BlobInfo:
    name: str
    # Changes whenever the blob is rewritten (GCS generation, or mtime for local files).
    generation: str
    size: int


class BlobStore(ABC):
    root_uri: str

    @abstractmethod
    def read(self, name: str) -> bytes | None:
        """The blob's bytes, or None if it doesn't exist."""

    @abstractmethod
    def write(self, name: str, data: bytes, content_type: str) -> str:
        """Write the blob and return its new generation."""

    @abstractmethod
    def download(self, name: str, dest: Path) -> None: ...

    @abstractmethod
    def list_blobs(self, prefix: str = "") -> list[BlobInfo]:
        """Every blob under prefix, recursively."""

    @abstractmethod
    def list_dirs(self, prefix: str = "") -> list[str]:
        """Names of the folders directly under prefix ("" = the root)."""

    def stat(self, name: str) -> BlobInfo | None:
        """One blob's info, or None if it doesn't exist."""
        for b in self.list_blobs(name):
            if b.name == name:
                return b
        return None

    def uri(self, name: str = "") -> str:
        return f"{self.root_uri.rstrip('/')}/{name}" if name else self.root_uri

    def child(self, folder: str) -> "BlobStore":
        """A store rooted at a subfolder."""
        return make_store(self.uri(folder.strip("/")))


class LocalStore(BlobStore):
    def __init__(self, root: Path):
        self.root = root
        self.root_uri = str(root)

    def _path(self, name: str) -> Path:
        return self.root.joinpath(*name.split("/"))

    def read(self, name: str) -> bytes | None:
        try:
            return self._path(name).read_bytes()
        except FileNotFoundError:
            return None

    def write(self, name: str, data: bytes, content_type: str) -> str:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return str(path.stat().st_mtime_ns)

    def download(self, name: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(name), dest)

    def list_blobs(self, prefix: str = "") -> list[BlobInfo]:
        base = self._path(prefix) if prefix else self.root
        if not base.is_dir():
            return []
        out = []
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".tmp"):
                    continue
                p = Path(dirpath) / f
                st = p.stat()
                rel = p.relative_to(self.root).as_posix()
                out.append(BlobInfo(rel, str(st.st_mtime_ns), st.st_size))
        out.sort(key=lambda b: b.name)
        return out

    def list_dirs(self, prefix: str = "") -> list[str]:
        base = self._path(prefix.strip("/")) if prefix.strip("/") else self.root
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())

    def stat(self, name: str) -> BlobInfo | None:
        path = self._path(name)
        if not path.is_file():
            return None
        st = path.stat()
        return BlobInfo(name, str(st.st_mtime_ns), st.st_size)


class GcsStore(BlobStore):
    _client = None
    _client_lock = threading.Lock()

    def __init__(self, bucket: str, prefix: str = ""):
        self.bucket_name = bucket
        self.prefix = f"{prefix.strip('/')}/" if prefix.strip("/") else ""
        self.root_uri = f"gs://{bucket}/{self.prefix}".rstrip("/")

    @classmethod
    def client(cls):
        # Created on first use so the server starts before credentials exist.
        with cls._client_lock:
            if cls._client is None:
                from google.cloud import storage

                cls._client = storage.Client()
            return cls._client

    def _blob(self, name: str):
        return self.client().bucket(self.bucket_name).blob(self.prefix + name)

    def read(self, name: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        try:
            return self._blob(name).download_as_bytes()
        except NotFound:
            return None

    def write(self, name: str, data: bytes, content_type: str) -> str:
        blob = self._blob(name)
        if content_type == "application/json":
            blob.cache_control = "no-cache"
        blob.upload_from_string(data, content_type=content_type)
        return str(blob.generation)

    def download(self, name: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        self._blob(name).download_to_filename(str(tmp))
        os.replace(tmp, dest)

    def list_blobs(self, prefix: str = "") -> list[BlobInfo]:
        full = self.prefix + prefix
        out = []
        for b in self.client().list_blobs(self.bucket_name, prefix=full):
            if b.name.endswith("/"):
                continue  # folder placeholder objects
            out.append(BlobInfo(b.name[len(self.prefix) :], str(b.generation), b.size or 0))
        return out

    def list_dirs(self, prefix: str = "") -> list[str]:
        full = self.prefix + (prefix.strip("/") + "/" if prefix.strip("/") else "")
        it = self.client().list_blobs(self.bucket_name, prefix=full, delimiter="/")
        for _ in it:
            pass  # prefixes are filled in while paging
        return sorted(p[len(full) :].rstrip("/") for p in it.prefixes)

    def stat(self, name: str) -> BlobInfo | None:
        blob = self.client().bucket(self.bucket_name).get_blob(self.prefix + name)
        return BlobInfo(name, str(blob.generation), blob.size or 0) if blob else None


def make_store(spec: str) -> BlobStore:
    """ "gs://bucket/prefix", "file:///path" or a plain local path."""
    if spec.startswith("gs://"):
        bucket, _, prefix = spec[5:].partition("/")
        if not bucket:
            raise ValueError("A gs:// location needs a bucket name.")
        return GcsStore(bucket, prefix)
    if spec.startswith("file://"):
        spec = spec[7:].lstrip("/") if os.name == "nt" else spec[7:]
    return LocalStore(Path(spec))
