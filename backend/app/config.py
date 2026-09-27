from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://recorder:recorder@localhost:5432/recorder"
    # Hosted Postgres (e.g. Supabase's pooler) caps connections per project, so keep the pool small.
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # "recorder": checks channels, records and uploads. "viewer": serves the page and API from the
    # shared database only (for other machines); live updates arrive from the recorder via NOTIFY.
    role: str = "recorder"

    # Local buffer for segments waiting to be uploaded.
    spool_dir: Path = Path("./spool")

    # "gcs" uploads to Cloud Storage (credentials from GOOGLE_APPLICATION_CREDENTIALS or the VM's
    # service account). "local" copies into local_storage_dir, for development without credentials.
    storage_backend: str = "gcs"
    local_storage_dir: Path = Path("./local-bucket")
    gcs_bucket: str = "mmohighlights"
    # The bucket's GCP project (id or number). Optional; only needed for some credential types.
    gcs_project: str = ""
    gcs_prefix: str = "archives/"
    upload_workers: int = 4
    retention_days: int = 90

    poll_interval_s: float = 30.0
    poll_jitter_s: float = 3.0
    checks_failed_before_error: int = 3

    segment_seconds: int = 300
    # A recording is finalized only after the stream has been offline this long.
    grace_period_s: int = 600
    # Offline polls in a row before a running recording moves to "ending".
    offline_polls_to_end: int = 2
    quality: str = "1080p60,1080p,720p60,720p,best"
    max_channels: int = 10

    # Estimated delay of the video behind chat (HLS buffering), per platform.
    chat_offset_twitch_s: float = 8.0
    chat_offset_youtube_s: float = 10.0
    chat_offset_chzzk_s: float = 8.0

    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    youtube_api_key: str = ""
    # Cookies from a logged-in Naver account; only needed for age-restricted Chzzk streams.
    chzzk_nid_aut: str = ""
    chzzk_nid_ses: str = ""

    # Disable background loops (poller, recorder, uploader); used by tests.
    run_workers: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def normalized_prefix(self) -> str:
        p = self.gcs_prefix.strip("/")
        return f"{p}/" if p else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
