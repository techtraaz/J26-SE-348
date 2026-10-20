"""S3-compatible object storage (Garage, MinIO, AWS S3), behind the same
Storage interface as local disk: callers do not change.

Keys are the same relative paths as on disk ("documents/<id>/pages/1.original.png")
and become object keys in one bucket.
"""

import mimetypes
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.services.storage.base import Storage

_MISSING = {"404", "NoSuchKey", "NotFound"}
_DELETE_BATCH = 1000  # the most objects one DeleteObjects request may name


def _check_key(key: str) -> str:
    """The same rule as local disk: relative, no "..", never empty."""
    parts = key.split("/")
    if not key or key.startswith("/") or "\\" in key or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"Invalid storage key: {key!r}")
    return key


class S3Storage(Storage):
    def __init__(self, client: Any, bucket: str) -> None:
        self._s3 = client
        self._bucket = bucket

    @classmethod
    def connect(cls, endpoint: str, access_key: str, secret_key: str, bucket: str, region: str) -> "S3Storage":
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            # Garage (like MinIO) wants path-style URLs and signature v4.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        return cls(client, bucket)

    def check(self) -> None:
        """Fail fast at startup when the bucket is unreachable or the keys are wrong."""
        try:
            self._s3.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            raise RuntimeError(f"Object storage bucket {self._bucket!r} is not usable ({code or exc}).") from exc

    def save(self, key: str, data: bytes) -> None:
        # One PUT replaces the object atomically: readers see the old or the new bytes.
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self._s3.put_object(Bucket=self._bucket, Key=_check_key(key), Body=data, ContentType=content_type)

    def load(self, key: str) -> bytes:
        try:
            return self._s3.get_object(Bucket=self._bucket, Key=_check_key(key))["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                raise FileNotFoundError(key) from exc
            raise

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=_check_key(key))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                return False
            raise

    def delete_prefix(self, prefix: str) -> None:
        prefix = _check_key(prefix.rstrip("/"))
        keys: list[str] = []
        # "documents/<id>/..." and an object named exactly "documents/<id>", but
        # never "documents/<id>X...": the prefix is matched on whole path segments.
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", []) if o["Key"] == prefix or o["Key"].startswith(prefix + "/")]
        for start in range(0, len(keys), _DELETE_BATCH):
            batch = [{"Key": k} for k in keys[start:start + _DELETE_BATCH]]
            self._s3.delete_objects(Bucket=self._bucket, Delete={"Objects": batch, "Quiet": True})
