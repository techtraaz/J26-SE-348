"""Storage interface for uploaded files and page images.

Keys are relative, slash-separated paths such as
"documents/<id>/pages/1.original.png". Two stores implement it: local disk
(local.py) and S3-compatible object storage such as Garage (s3.py), chosen by
settings in factory.py; callers never know which one they use.
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

    def check(self) -> None:  # an optional hook: a no-op by default
        """Raise if the store cannot be used, so the app fails at startup
        rather than on the first upload."""