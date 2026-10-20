"""Storage interface for uploaded files and page images.

Keys are relative, slash-separated paths such as
"documents/<id>/pages/1.original.png". Local disk for now; the interface lets
another store replace it without touching callers.
"""

from abc import ABC, abstractmethod

class Storage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> None:
        """Write `data` at `key`, replacing anything already there."""

    @abstractmethod
    def load(self, key: str) -> bytes:
        """Return the bytes at `key`. Raises FileNotFoundError if absent."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """Remove every file under `prefix` (e.g. "documents/<id>"). No error
        if nothing is there."""