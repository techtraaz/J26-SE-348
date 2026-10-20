import mongomock
import pytest

from app.services import intake, orchestrator
from app.services.store import MongoStore, StoreError
from tests.conftest import doc


@pytest.fixture
def mongo():
    return MongoStore(uri="mongodb://fake", db_name="nomos_test", client=mongomock.MongoClient())


def _case():
    return intake.normalize_case({"case_id": "M", "docs": [
        doc("BS", "balance_sheet", {"assets": 100, "liabilities": 30, "capital": 20})]})


def test_mongo_store_keeps_every_version(kg, mongo):
    first = orchestrator.run_case(_case(), kg, store=mongo)
    second = orchestrator.run_case(_case(), kg, store=mongo)
    assert (first.version, second.version) == (1, 2)
    assert [v["version"] for v in mongo.versions("M")] == [1, 2]
    assert mongo.versions("M")[0]["findings"] == len(first.findings)
    rec = mongo.get("M", 1)
    assert rec["_id"] == "M:v1" and rec["case"]["docs"][0]["doc_id"] == "BS"
    assert mongo.latest("M")["version"] == 2
    assert all(f["supersedes"] == 1 for f in mongo.latest("M")["findings"])


def test_mongo_duplicate_version_is_refused(kg, mongo):
    result = orchestrator.run_case(_case(), kg, store=mongo)
    with pytest.raises(StoreError):
        mongo.save(_case(), result)


def test_mongo_without_uri_fails_loudly():
    with pytest.raises(StoreError):
        MongoStore(uri="").latest("M")
