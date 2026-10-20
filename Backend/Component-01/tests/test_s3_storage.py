"""S3-compatible storage (Garage in deployment), tested against moto's in-memory S3.

Garage is reached on its own endpoint, so moto is told to answer for that
endpoint too (MOTO_S3_CUSTOM_ENDPOINTS).
"""

import io

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from PIL import Image

from app.main import create_app
from app.services.storage.factory import create_storage
from app.services.storage.local import LocalStorage
from app.services.storage.s3 import S3Storage
from tests.conftest import make_png

ENDPOINT = "http://garage.test:3900"
BUCKET = "nomos-c1"
GARAGE = {"s3_endpoint": ENDPOINT, "s3_access_key": "GK-test", "s3_secret_key": "secret", "s3_bucket": BUCKET}


@pytest.fixture
def s3(monkeypatch):
    """A moto S3 answering on the Garage endpoint, with the bucket created."""
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", ENDPOINT)
    with mock_aws():
        client = boto3.client(
            "s3", endpoint_url=ENDPOINT, aws_access_key_id="GK-test",
            aws_secret_access_key="secret", region_name="us-east-1",
        )
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def storage(s3):
    return S3Storage.connect(ENDPOINT, "GK-test", "secret", BUCKET, region="us-east-1")


def _keys(s3) -> list[str]:
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []))


# ---- the Storage contract, as local disk keeps it ---------------------------


def test_save_load_exists_round_trip(storage, s3):
    storage.save("documents/a/original.png", b"\x89PNG data")

    assert storage.load("documents/a/original.png") == b"\x89PNG data"
    assert storage.exists("documents/a/original.png")
    assert not storage.exists("documents/a/other.png")
    head = s3.head_object(Bucket=BUCKET, Key="documents/a/original.png")
    assert head["ContentType"] == "image/png"


def test_save_replaces_existing(storage):
    storage.save("documents/a/original.pdf", b"one")
    storage.save("documents/a/original.pdf", b"two")

    assert storage.load("documents/a/original.pdf") == b"two"


def test_missing_key_raises_file_not_found(storage):
    with pytest.raises(FileNotFoundError):
        storage.load("documents/nope.bin")


@pytest.mark.parametrize("key", ["", "/abs/path.png", "../outside.png", "documents/../x.png", "a//b.png", "a\\b.png"])
def test_unsafe_keys_are_rejected(storage, key):
    with pytest.raises(ValueError):
        storage.save(key, b"x")
    with pytest.raises(ValueError):
        storage.load(key)
    with pytest.raises(ValueError):
        storage.delete_prefix(key)


def test_delete_prefix_removes_the_document_and_nothing_else(storage, s3):
    storage.save("documents/abc/original.png", b"1")
    storage.save("documents/abc/pages/1.original.png", b"2")
    storage.save("documents/abcd/original.png", b"3")  # shares the text prefix, not the folder

    storage.delete_prefix("documents/abc")
    storage.delete_prefix("documents/missing")  # nothing there: no error

    assert _keys(s3) == ["documents/abcd/original.png"]


def test_delete_prefix_handles_more_objects_than_one_request_can_name(storage, s3):
    for i in range(1005):
        s3.put_object(Bucket=BUCKET, Key=f"documents/big/pages/{i}.png", Body=b"")

    storage.delete_prefix("documents/big")

    assert _keys(s3) == []


# ---- startup ---------------------------------------------------------------


def test_check_passes_for_a_usable_bucket_and_names_a_missing_one(s3):
    S3Storage.connect(ENDPOINT, "GK-test", "secret", BUCKET, region="us-east-1").check()

    with pytest.raises(RuntimeError, match="'no-such-bucket'"):
        S3Storage.connect(ENDPOINT, "GK-test", "secret", "no-such-bucket", region="us-east-1").check()


def test_the_factory_picks_the_store_from_settings(make_settings, s3):
    assert isinstance(create_storage(make_settings()), LocalStorage)  # the default
    assert isinstance(create_storage(make_settings(storage_backend="s3", **GARAGE)), S3Storage)


def test_object_storage_needs_its_connection_settings(make_settings):
    with pytest.raises(ValueError, match="GARAGE_ENDPOINT"):
        make_settings(storage_backend="s3", s3_access_key="k", s3_secret_key="s")


# ---- the whole app on object storage ---------------------------------------


def test_upload_extract_serve_and_delete_on_object_storage(make_settings, s3):
    with TestClient(create_app(make_settings(storage_backend="s3", **GARAGE))) as client:
        assert client.get("/api/v1/health").json()["storage"] == "s3"
        doc_id = client.post("/api/v1/documents", files={"file": ("scan.png", make_png())}).json()["id"]
        assert client.app.state.worker.run_once() is True

        image = client.get(f"/api/v1/documents/{doc_id}/pages/1/image")
        assert image.status_code == 200
        assert Image.open(io.BytesIO(image.content)).size == (200, 100)
        assert f"documents/{doc_id}/original.png" in _keys(s3)  # nothing on local disk

        assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 204
        assert not [k for k in _keys(s3) if k.startswith(f"documents/{doc_id}/")]


def test_the_app_does_not_start_when_the_bucket_is_unusable(make_settings, s3):
    app = create_app(make_settings(storage_backend="s3", **{**GARAGE, "s3_bucket": "no-such-bucket"}))

    with pytest.raises(RuntimeError, match="no-such-bucket"), TestClient(app):
        pass


# ---- moving an existing local store into the bucket -------------------------


def test_copy_store_moves_local_files_into_the_bucket_once(tmp_path, storage, s3):
    from scripts.copy_store_to_s3 import copy_store

    local = LocalStorage(tmp_path / "store")
    local.save("documents/a/original.png", b"1")
    local.save("documents/a/pages/1.original.png", b"2")
    (tmp_path / "store" / "documents" / "a" / "half.png.tmp").write_bytes(b"x")  # an interrupted write

    assert copy_store(tmp_path / "store", storage, dry_run=True) == {"copied": 2, "skipped": 0}
    assert _keys(s3) == []  # a dry run writes nothing

    assert copy_store(tmp_path / "store", storage) == {"copied": 2, "skipped": 0}
    assert _keys(s3) == ["documents/a/original.png", "documents/a/pages/1.original.png"]
    assert storage.load("documents/a/pages/1.original.png") == b"2"

    assert copy_store(tmp_path / "store", storage) == {"copied": 0, "skipped": 2}  # safe to run again
