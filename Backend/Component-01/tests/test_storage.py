import pytest

from app.services.storage.local import LocalStorage


def test_save_load_exists_round_trip(tmp_path):
    storage = LocalStorage(tmp_path)

    assert not storage.exists("documents/a/original.pdf")
    storage.save("documents/a/original.pdf", b"data")

    assert storage.exists("documents/a/original.pdf")
    assert storage.load("documents/a/original.pdf") == b"data"


def test_save_replaces_existing_and_leaves_no_temp_file(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.save("k/x.bin", b"one")
    storage.save("k/x.bin", b"two")

    assert storage.load("k/x.bin") == b"two"
    assert [p.name for p in (tmp_path / "k").iterdir()] == ["x.bin"]


def test_missing_key_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        LocalStorage(tmp_path).load("nope.bin")


@pytest.mark.parametrize("key", ["../evil.txt", "a/../../evil.txt", "/etc/passwd", "", "."])
def test_keys_outside_the_root_are_rejected(tmp_path, key):
    storage = LocalStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.save(key, b"x")
    with pytest.raises(ValueError):
        storage.exists(key)