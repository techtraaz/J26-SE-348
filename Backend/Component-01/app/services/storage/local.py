"""Local-disk storage under one root folder."""

import os
import shutil
from pathlib import Path

from app.services.storage.base import Storage

class LocalStorage(Storage):
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        # Reject absolute keys and "..": nothing may resolve outside the root.
        if path == self._root or not path.is_relative_to(self._root):
            raise ValueError(f"Invalid storage key: {key!r}")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a reader never sees a half-written file.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix)  # the same root check: never outside the store
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()