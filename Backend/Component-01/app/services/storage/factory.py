"""Build the store the settings ask for (NOMOS_STORAGE_BACKEND)."""

from app.core.config import Settings
from app.services.storage.base import Storage
from app.services.storage.local import LocalStorage


def create_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        # Imported here: boto3 is only needed when this store is used.
        from app.services.storage.s3 import S3Storage

        return S3Storage.connect(
            endpoint=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key.get_secret_value(),
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    return LocalStorage(settings.storage_root)
