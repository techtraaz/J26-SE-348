import openai
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.query import search

STANDARDS = [{"code": "LKAS 1"}, {"code": "LKAS 2"}]


def _hit(section, score, via="keyword", matched="Section"):
    return {"section": section, "paragraph": section.split(":")[1], "heading": "h", "text": "t",
            "standard": section.split(":")[0], "title": "x", "status": "active", "page": 1,
            "file": "f.pdf", "matched": matched, "matched_id": section, "score": score, "via": via}


class FakeRun:
    def __init__(self, keyword=(), semantic=(), exact=()):
        self.keyword, self.semantic, self.exact = list(keyword), list(semantic), list(exact)
        self.calls = []

    def __call__(self, query, **params):
        self.calls.append((query, params))
        if "MATCH (s:Standard) RETURN" in query:
            return STANDARDS
        if "fulltext" in query:
            return self.keyword
        if "vector" in query:
            return self.semantic
        if "{id: $id}" in query:
            return self.exact
        return []


def test_escape_lucene_special_characters():
    assert search.escape_lucene("LKAS 2:9") == "LKAS 2\\:9"
    assert search.escape_lucene('"cost" (NRV)?') == '\\"cost\\" \\(NRV\\)\\?'


def test_paragraph_reference_goes_first():
    run = FakeRun(keyword=[_hit("LKAS 2:33", 18.0)], exact=[_hit("LKAS 2:9", 0, via="reference")])
    out = search.search("LKAS 2:9", mode="keyword", run=run)
    assert out["results"][0]["section"] == "LKAS 2:9"
    assert out["results"][0]["via"] == "reference"
    assert any(p.get("id") == "LKAS 2:9" for _, p in run.calls)


def test_keyword_keeps_one_hit_per_paragraph():
    run = FakeRun(keyword=[_hit("LKAS 2:36", 7.6), _hit("LKAS 2:36", 5.0, matched="Requirement"),
                           _hit("LKAS 2:34", 4.0)])
    hits = search.keyword_search("pledged", run=run)
    assert [h["section"] for h in hits] == ["LKAS 2:36", "LKAS 2:34"]
    assert hits[0]["matched"] == ["Section", "Requirement"] and hits[0]["score"] == 7.6


def test_keyword_query_is_escaped_and_filtered_by_parameter():
    run = FakeRun()
    search.keyword_search("LKAS 2:9", standard="LKAS 2", run=run)
    _, params = run.calls[0]
    assert params["q"] == "LKAS 2\\:9" and params["standard"] == "LKAS 2"


def test_hybrid_fuses_keyword_and_semantic():
    run = FakeRun(keyword=[_hit("LKAS 2:33", 18), _hit("LKAS 2:9", 5)],
                  semantic=[_hit("LKAS 2:9", 0.91, "semantic"), _hit("LKAS 2:6", 0.88, "semantic")])
    out = search.search("lower of cost and NRV", run=run, embed=lambda texts: [[0.1] * 4])
    assert out["results"][0]["section"] == "LKAS 2:9"
    assert out["results"][0]["via"] == "keyword+semantic"
    assert {h["section"] for h in out["results"]} == {"LKAS 2:9", "LKAS 2:33", "LKAS 2:6"}


def test_semantic_unavailable_with_fake_provider(monkeypatch):
    monkeypatch.setattr(search, "semantic_available", lambda: False)
    out = search.search("cash equivalents", mode="semantic", run=FakeRun())
    assert out["results"] == [] and "real embedding model" in out["note"]


def test_semantic_server_error_falls_back_to_keyword():
    def broken(texts):
        raise openai.APIConnectionError(request=None)
    run = FakeRun(keyword=[_hit("LKAS 7:7", 3.0)])
    out = search.search("cash equivalents", run=run, embed=broken)
    assert [h["section"] for h in out["results"]] == ["LKAS 7:7"]
    assert out["note"].startswith("semantic search unavailable")


@pytest.mark.parametrize("params", [{"q": "x"}, {"q": "cash", "mode": "nope"},
                                    {"q": "cash", "limit": 0}, {"q": "cash", "limit": 99}])
def test_endpoint_validates_parameters(params):
    assert TestClient(app).get("/query/search", params=params).status_code == 422


def test_endpoint_passes_options(monkeypatch):
    seen = []
    monkeypatch.setattr(search, "search", lambda *a: seen.append(a) or {"results": []})
    TestClient(app).get("/query/search", params={"q": "going concern", "mode": "keyword",
                                                 "limit": 5, "standard": "LKAS 1"})
    assert seen == [("going concern", "keyword", 5, "LKAS 1")]
