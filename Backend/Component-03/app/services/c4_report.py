"""Ask Component-04 for the PDF report of one saved audit version.

C3 sends which audit (case and version); C4 reads that saved result from
MongoDB and builds the PDF from C3's data only. The agreed request is

    POST {C4_URL}/report/generate   {"audit_id": "<case_id>:v<version>", "case_id": ..., "version": ...}

Until C4 serves it, C4's older `POST /report/generate/{case_id}` is used.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from app import config


class C4Unavailable(RuntimeError):
    """C4 could not be reached or did not make the report."""


def _post(url: str, body: dict | None, timeout: float) -> tuple[int, object]:
    """(HTTP status, JSON reply). Raises C4Unavailable when C4 cannot be reached."""
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8") or "null")
        except json.JSONDecodeError:
            detail = None
        return exc.code, detail
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise C4Unavailable(f"Component-04 not reachable at {config.C4_URL}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise C4Unavailable("Component-04 replied with invalid JSON") from exc


def audit_id(case_id: str, version: int) -> str:
    """The saved result's id in nomos_xai.c03_audit_results."""
    return f"{case_id}:v{version}"


def request_report(case_id: str, version: int) -> dict:
    """C4's reply with `report_url` made absolute. Raises C4Unavailable."""
    base = config.C4_URL.rstrip("/")
    if not base:
        raise C4Unavailable("C4_URL is not configured")
    body = {"audit_id": audit_id(case_id, version), "case_id": case_id, "version": version}
    status, reply = _post(f"{base}/report/generate", body, config.C4_TIMEOUT)
    if status in (404, 405) and not (isinstance(reply, dict) and reply.get("download_url")):
        # C4 does not serve the agreed endpoint yet: its older one takes the case id only.
        status, reply = _post(f"{base}/report/generate/{urllib.parse.quote(case_id, safe='')}",
                              None, config.C4_TIMEOUT)
    if status >= 400 or not isinstance(reply, dict):
        why = reply.get("detail") if isinstance(reply, dict) else None
        raise C4Unavailable(f"Component-04 could not make the report (HTTP {status}"
                            f"{': ' + str(why) if why else ''})")
    url = reply.get("download_url") or reply.get("report_url")
    if isinstance(url, str) and url.startswith("/"):
        url = base + url
    return {**reply, "report_url": url}
