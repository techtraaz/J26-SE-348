import json
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings


class StorageError(RuntimeError):
    pass


class StorageNotConfigured(StorageError):
    pass


class NotFound(StorageError):
    pass


@dataclass
class StoredObject:
    key: str
    size: int
    last_modified: str


class ObjectStore:
    """Thin wrapper over an S3 client (Garage) for one bucket."""

    def __init__(self, client, bucket: str):
        self.client = client
        self.bucket = bucket

    def _call(self, fn, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            return fn(Bucket=self.bucket, **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise NotFound(kwargs.get("Key", "")) from exc
            raise StorageError(f"Object storage error: {code or type(exc).__name__}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"Object storage unreachable: {type(exc).__name__}") from exc

    def ping(self) -> None:
        """Raises StorageError when the bucket cannot be reached."""
        self._call(self.client.head_bucket)

    def put(self, key: str, data: bytes, content_type: str,
            metadata: dict[str, str] | None = None) -> None:
        self._call(self.client.put_object, Key=key, Body=data, ContentType=content_type,
                   Metadata=metadata or {})

    def get(self, key: str) -> tuple[bytes, str]:
        resp = self._call(self.client.get_object, Key=key)
        return resp["Body"].read(), resp.get("ContentType", "application/octet-stream")

    def head(self, key: str) -> dict:
        resp = self._call(self.client.head_object, Key=key)
        return {"size": resp.get("ContentLength", 0), "metadata": resp.get("Metadata", {}),
                "last_modified": resp["LastModified"].isoformat()}

    def list(self, prefix: str) -> list[StoredObject]:
        out, token = [], None
        while True:
            kwargs = {"Prefix": prefix, **({"ContinuationToken": token} if token else {})}
            resp = self._call(self.client.list_objects_v2, **kwargs)
            out += [StoredObject(o["Key"], o["Size"], o["LastModified"].isoformat())
                    for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return out
            token = resp.get("NextContinuationToken")

    def put_json(self, key: str, data: dict) -> None:
        self.put(key, json.dumps(data, default=str).encode(), "application/json")

    def get_json(self, key: str) -> dict | None:
        try:
            return json.loads(self.get(key)[0])
        except NotFound:
            return None


def _client(s: Settings):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=s.garage_endpoint, aws_access_key_id=s.garage_access_key,
        aws_secret_access_key=s.garage_secret_key, region_name="garage",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}))


@lru_cache
def get_store() -> ObjectStore:
    s = get_settings()
    if not (s.garage_endpoint and s.garage_access_key and s.garage_secret_key):
        raise StorageNotConfigured(
            "Object storage is not configured: set GARAGE_ENDPOINT, GARAGE_ACCESS_KEY and "
            "GARAGE_SECRET_KEY in Component-02/.env")
    return ObjectStore(_client(s), s.garage_bucket)
