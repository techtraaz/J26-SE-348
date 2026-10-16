from datetime import datetime, timezone

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on PostgreSQL (indexable, queryable for analysis), plain JSON elsewhere
# (SQLite in unit tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)