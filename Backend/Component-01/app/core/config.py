"""Application settings.
Every value can be overridden with an environment variable prefixed or from a `.env` file in the
folder the server is started from."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.ingestion.models import DEFAULT_PDF_DPI, IngestionLimits

BACKEND_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    # populate_by_name: code and tests can also pass s3_* by field name.
    model_config = SettingsConfigDict(env_prefix="NOMOS_", env_file=".env", extra="ignore", populate_by_name=True)

    # "paddle" is the honest default. Use "replay" for app development:
    # real OCR takes about a minute per page on the dev laptop.
    engine: Literal["paddle", "replay"] = "paddle"
    replay_fixture: Path = BACKEND_ROOT / "tests" / "fixtures" / "sample_invoice.default.json"
    replay_delay_s: float = 0.0

    # Where uploaded files and page images live: "local" disk (storage_root) or
    # an S3-compatible object store such as Garage ("s3", the GARAGE_* settings).
    storage_backend: Literal["local", "s3"] = "local"
    storage_root: Path = BACKEND_ROOT / "data" / "store"
    # Object storage. Named GARAGE_* (no NOMOS_ prefix), as the team's Garage setup uses.
    s3_endpoint: str | None = Field(default=None, validation_alias="GARAGE_ENDPOINT")
    s3_access_key: str | None = Field(default=None, validation_alias="GARAGE_ACCESS_KEY")
    s3_secret_key: SecretStr | None = Field(default=None, validation_alias="GARAGE_SECRET_KEY")
    s3_bucket: str = Field(default="uploads", validation_alias="GARAGE_BUCKET")
    s3_region: str = Field(default="garage", validation_alias="GARAGE_REGION")

    # Put real password in .env.
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/nomos"

    pdf_dpi: int = DEFAULT_PDF_DPI
    max_file_bytes: int = 25 * 1024 * 1024
    max_pages: int = 20
    max_pixels_per_page: int = 40_000_000

    # The background worker runs inside the API process.
    run_worker: bool = True
    worker_poll_interval_s: float = 1.0

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="after")
    def _object_storage_is_complete(self) -> "Settings":
        if self.storage_backend == "s3":
            missing = [name for name, value in (
                ("GARAGE_ENDPOINT", self.s3_endpoint),
                ("GARAGE_ACCESS_KEY", self.s3_access_key),
                ("GARAGE_SECRET_KEY", self.s3_secret_key),
            ) if not value]
            if missing:
                raise ValueError(f"NOMOS_STORAGE_BACKEND=s3 needs {', '.join(missing)}.")
        return self

    @property
    def limits(self) -> IngestionLimits:
        return IngestionLimits(
            max_file_bytes=self.max_file_bytes,
            max_pages=self.max_pages,
            max_pixels_per_page=self.max_pixels_per_page,
        )