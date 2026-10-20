"""Copy the local file store into object storage, once, before switching
NOMOS_STORAGE_BACKEND from local to s3. Documents uploaded so far keep working:
their files get the same keys in the bucket.

Run from the backend folder (GARAGE_* settings come from .env):
    uv run python scripts/copy_store_to_s3.py --dry-run     # list what would be copied
    uv run python scripts/copy_store_to_s3.py               # copy what is not in the bucket yet

Safe to run again: files already in the bucket are skipped (--overwrite replaces them).
"""

import argparse
import sys
from pathlib import Path

# Make `app` importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings
from app.services.storage.factory import create_storage
from app.services.storage.local import LocalStorage


def copy_store(local_root: Path, target, *, dry_run: bool = False, overwrite: bool = False) -> dict[str, int]:
    """Copy every file under `local_root` to `target` (a Storage) under the same key."""
    local = LocalStorage(local_root)
    counts = {"copied": 0, "skipped": 0}
    for path in sorted(p for p in local_root.rglob("*") if p.is_file() and not p.name.endswith(".tmp")):
        key = path.relative_to(local_root).as_posix()
        if not overwrite and target.exists(key):
            counts["skipped"] += 1
            continue
        if not dry_run:
            target.save(key, local.load(key))
        counts["copied"] += 1
        print(("would copy " if dry_run else "copied ") + key)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only list what would be copied")
    parser.add_argument("--overwrite", action="store_true", help="replace files already in the bucket")
    args = parser.parse_args()

    settings = Settings(storage_backend="s3")  # the GARAGE_* settings from .env
    target = create_storage(settings)
    target.check()
    print(f"{settings.storage_root} -> bucket {settings.s3_bucket!r} at {settings.s3_endpoint}")
    counts = copy_store(settings.storage_root, target, dry_run=args.dry_run, overwrite=args.overwrite)
    verb = "would copy" if args.dry_run else "copied"
    print(f"{verb} {counts['copied']} file(s), skipped {counts['skipped']} already in the bucket.")


if __name__ == "__main__":
    main()
