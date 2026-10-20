"""MongoDB storage for the Review Agent's results and the trace reader's position.

- ``c04_reviews``: one document per reviewed run (an audit run or a Copilot
  turn), keyed by its run_key. Kept until the user deletes the chat (Copilot
  turns) — audit reviews stay with their audit.
- ``c04_reader_state``: the id of the last trace event the reader processed,
  so a restart continues from there instead of re-reading every trace.

All calls go through report_store's shared connection and worker threads.
"""

from __future__ import annotations

from typing import Any

from app import config
from app.services import report_store

_REVIEW_FIELDS = ("event_type", "case_id", "stream_id", "run_key", "run_kind", "agent_name", "verdict",
                  "headline", "summary", "next_steps", "source", "model", "generated_at")


# ── Reviews ────────────────────────────────────────────────────────────

def _save_review(review: dict) -> None:
    col = report_store.database()[config.REVIEWS_COLLECTION]
    col.create_index([("case_id", 1), ("generated_at", 1)])
    col.create_index("stream_id")
    doc = {k: review.get(k) for k in _REVIEW_FIELDS}
    col.replace_one({"_id": review["run_key"]}, {**doc, "_id": review["run_key"]}, upsert=True)


def _get_review(run_key: str) -> dict | None:
    return report_store.database()[config.REVIEWS_COLLECTION].find_one({"_id": run_key}, {"_id": 0})


def _reviews_for_stream(stream_id: str) -> list[dict]:
    col = report_store.database()[config.REVIEWS_COLLECTION]
    return list(col.find({"$or": [{"case_id": stream_id}, {"stream_id": stream_id}]}, {"_id": 0})
                .sort("generated_at", 1))


def _delete_chat_reviews(stream_id: str) -> int:
    col = report_store.database()[config.REVIEWS_COLLECTION]
    return col.delete_many({"case_id": stream_id, "run_kind": "copilot"}).deleted_count


async def save_review(review: dict) -> None:
    await report_store.run(_save_review, review)


async def get_review(run_key: str) -> dict | None:
    return await report_store.run(_get_review, run_key)


async def reviews_for_stream(stream_id: str) -> list[dict]:
    return await report_store.run(_reviews_for_stream, stream_id)


async def delete_chat_reviews(stream_id: str) -> int:
    """Remove the reviews of a deleted chat's Copilot turns (audit reviews are kept)."""
    return await report_store.run(_delete_chat_reviews, stream_id)


# ── Trace reader position ──────────────────────────────────────────────

_READER = "trace_reader"


def _get_position() -> Any:
    doc = report_store.database()[config.READER_STATE_COLLECTION].find_one({"_id": _READER})
    return doc.get("last_id") if doc else None


def _set_position(last_id: Any) -> None:
    report_store.database()[config.READER_STATE_COLLECTION].update_one(
        {"_id": _READER}, {"$set": {"last_id": last_id}}, upsert=True)


async def get_position() -> Any:
    return await report_store.run(_get_position)


async def set_position(last_id: Any) -> None:
    await report_store.run(_set_position, last_id)
