from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on PostgreSQL (indexable, queryable for analysis), plain JSON elsewhere
# (SQLite in unit tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every database.

    PostgreSQL's timestamptz already does this; SQLite drops the timezone and
    returns naive values, which then cannot be compared with aware ones. This
    makes both behave the same.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:  # naive values are treated as UTC
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value