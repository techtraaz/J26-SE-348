"""Application settings.
Every value can be overridden with an environment variable prefixed or from a `.env` file in the
folder the server is started from."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.ingestion.models import DEFAULT_PDF_DPI, IngestionLimits

BACKEND_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOMOS_", env_file=".env", extra="ignore")

    # "paddle" is the honest default. Use "replay" for app development:
    # real OCR takes about a minute per page on the dev laptop.
    engine: Literal["paddle", "replay"] = "paddle"
    replay_fixture: Path = BACKEND_ROOT / "tests" / "fixtures" / "sample_invoice.default.json"
    replay_delay_s: float = 0.0

    storage_root: Path = BACKEND_ROOT / "data" / "store"
    
    # Put real password in .env.
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/nomos"

    pdf_dpi: int = DEFAULT_PDF_DPI
    max_file_bytes: int = 25 * 1024 * 1024
    max_pages: int = 20
    max_pixels_per_page: int = 40_000_000

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def limits(self) -> IngestionLimits:
        return IngestionLimits(
            max_file_bytes=self.max_file_bytes,
            max_pages=self.max_pages,
            max_pixels_per_page=self.max_pixels_per_page,
        )