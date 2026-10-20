"""Documents fetched straight from Component-01, for an audit run in one call.

Only C1's fixed GET endpoints are called (document details for the file name,
/verified for the verified record), with ids checked first. Fields are mapped as
the Library preview suggests them: rule matches as they are, AI matches capped
and flagged as unconfirmed (c1_review.confirm decides the confidences). A
document must be human-verified in C1; machine extractions go through the
Library review instead.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from pydantic import BaseModel, Field

from app import config
from app.schemas.c1 import C1VerifiedRecord
from app.services import intake
from app.services.c1_review import C1Input, FieldDecision, ReviewedDocument, preview
from app.services.kg_client import KGClient

Transport = Callable[[str], object]


class C1Unavailable(RuntimeError):
    """C1 could not be reached or did not reply with JSON."""


class C1DocumentRequest(BaseModel):
    document_id: str = Field(pattern=intake.SAFE_ID_RE.pattern)
    doc_type: str | None = None  # suggested from the document when absent
    period_year: int | None = None  # suggested from the document when absent
    parent_document_id: str | None = Field(None, pattern=intake.SAFE_ID_RE.pattern)


class C1Client:
    def __init__(self, base_url: str | None = None, timeout: float | None = None,
                 transport: Transport | None = None) -> None:
        self.base_url = (config.C1_URL if base_url is None else base_url).rstrip("/")
        self.timeout = config.C1_TIMEOUT if timeout is None else timeout
        self._get = transport or self._http_get

    def _http_get(self, path: str) -> object:
        if not self.base_url:
            raise C1Unavailable("C1_URL is not configured")
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # before URLError (subclass)
            if exc.code == 404:
                return None
            raise C1Unavailable(f"C1 returned HTTP {exc.code} for {path}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise C1Unavailable(f"C1 not reachable at {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise C1Unavailable(f"C1 replied with invalid JSON for {path}") from exc

    def document(self, document_id: str) -> dict | None:
        raw = self._get(f"/api/v1/documents/{urllib.parse.quote(document_id, safe='')}")
        return raw if isinstance(raw, dict) else None

    def verified(self, document_id: str) -> dict | None:
        raw = self._get(f"/api/v1/documents/{urllib.parse.quote(document_id, safe='')}/verified")
        return raw if isinstance(raw, dict) else None


def reviewed_documents(case_id: str, requests: list[C1DocumentRequest], kg: KGClient,
                       client: C1Client | None = None) -> list[ReviewedDocument]:
    """The requested C1 documents with the fields C3 maps from them. Raises
    LookupError for an unknown document and IntakeError when one cannot be used."""
    client = client or C1Client()
    out = []
    for req in requests:
        meta = client.document(req.document_id)
        if meta is None:
            raise LookupError(f"C1 has no document {req.document_id!r}")
        raw = client.verified(req.document_id)
        if raw is None:
            raise intake.IntakeError(
                f"{meta.get('filename') or req.document_id} is not verified in C1 yet "
                f"(status {meta.get('status', '?')}); confirm it in C1's review first")
        record = C1VerifiedRecord.model_validate(raw)
        name = meta.get("filename") if isinstance(meta.get("filename"), str) else None
        p = preview(case_id, [C1Input(verified=record, name=name, doc_type=req.doc_type)], kg)[0]
        year = req.period_year or (p["suggestions"]["period_year"] or {}).get("value")
        if not isinstance(year, int):
            raise intake.IntakeError(f"{name or req.document_id}: no year found; send period_year")
        out.append(ReviewedDocument(
            verified=record, name=name, doc_type=p["doc_type"], period_year=year,
            parent_doc_id=req.parent_document_id,
            fields=[FieldDecision(field=f["field"], line_id=f["line"]["line_id"]) for f in p["fields"]]))
    return out
