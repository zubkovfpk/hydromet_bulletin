import os
from pathlib import Path

import pytest

from utils.archive_rotation import ArchiveRotationError, rotate_archive


def test_rotate_archive_from_zero_slots(tmp_path):
    archive_root = tmp_path / "storage" / "archive" / "gfs"
    archive_root.mkdir(parents=True)
    current_storage_path = tmp_path / "storage" / "gfs" / "20260513" / "12z"
    _make_non_empty_dir(current_storage_path)

    result = rotate_archive("gfs", current_storage_path, archive_root)

    slots = _slot_dirs(archive_root)
    assert len(slots) == 1
    assert result == {"24h-back": slots[0], "48h-back": None}
    assert slots[0].name == "20260513_12z"
    assert not current_storage_path.exists()


def test_rotate_archive_from_one_slot(tmp_path):
    archive_root = tmp_path / "storage" / "archive" / "gfs"
    old_slot = archive_root / "20260512_18z"
    _make_non_empty_dir(old_slot, mtime=1_000)
    current_storage_path = tmp_path / "storage" / "gfs" / "20260513" / "00z"
    _make_non_empty_dir(current_storage_path, mtime=2_000)

    result = rotate_archive("gfs", current_storage_path, archive_root)

    slots = _slot_dirs(archive_root)
    assert len(slots) == 2
    assert result["24h-back"] == archive_root / "20260513_00z"
    assert result["48h-back"] == old_slot
    assert result["24h-back"] in slots
    assert result["48h-back"] in slots


def test_rotate_archive_from_two_slots_drops_oldest(tmp_path):
    archive_root = tmp_path / "storage" / "archive" / "gfs"
    oldest_slot = archive_root / "20260512_12z"
    middle_slot = archive_root / "20260512_18z"
    _make_non_empty_dir(oldest_slot, mtime=1_000)
    _make_non_empty_dir(middle_slot, mtime=2_000)
    current_storage_path = tmp_path / "storage" / "gfs" / "20260513" / "00z"
    _make_non_empty_dir(current_storage_path, mtime=3_000)

    result = rotate_archive("gfs", current_storage_path, archive_root)

    slots = _slot_dirs(archive_root)
    assert len(slots) == 2
    assert not oldest_slot.exists()
    assert middle_slot.exists()
    assert result["24h-back"] == archive_root / "20260513_00z"
    assert result["48h-back"] == middle_slot


def test_rotate_archive_raises_on_three_or_more_slots(tmp_path):
    archive_root = tmp_path / "storage" / "archive" / "gfs"
    for index, mtime in enumerate((1_000, 2_000, 3_000), start=1):
        _make_non_empty_dir(archive_root / f"slot-{index}", mtime=mtime)
    current_storage_path = tmp_path / "storage" / "gfs" / "20260513" / "00z"
    _make_non_empty_dir(current_storage_path)
    before_slots = {slot.name for slot in _slot_dirs(archive_root)}

    with pytest.raises(ArchiveRotationError, match="archive invariant violation"):
        rotate_archive("gfs", current_storage_path, archive_root)

    assert {slot.name for slot in _slot_dirs(archive_root)} == before_slots
    assert current_storage_path.exists()


@pytest.mark.parametrize("create_empty_dir", [False, True])
def test_rotate_archive_raises_on_empty_current_path(tmp_path, create_empty_dir):
    archive_root = tmp_path / "storage" / "archive" / "gfs"
    current_storage_path = tmp_path / "storage" / "gfs" / "20260513" / "00z"
    if create_empty_dir:
        current_storage_path.mkdir(parents=True)

    with pytest.raises(ArchiveRotationError, match="nothing to rotate"):
        rotate_archive("gfs", current_storage_path, archive_root)


def test_rotate_archive_creates_archive_root_if_missing(tmp_path):
    archive_root = tmp_path / "storage" / "archive" / "gfs"
    current_storage_path = tmp_path / "storage" / "gfs" / "20260513" / "18z"
    _make_non_empty_dir(current_storage_path)

    result = rotate_archive("gfs", current_storage_path, archive_root)

    assert archive_root.exists()
    assert len(_slot_dirs(archive_root)) == 1
    assert result["24h-back"] == archive_root / "20260513_18z"
    assert result["48h-back"] is None


def test_rotate_archive_conflict_on_existing_name(tmp_path):
    archive_root = tmp_path / "storage" / "archive" / "cmems"
    current_storage_path = tmp_path / "storage" / "cmems" / "20260513"
    conflicting_slot = archive_root / current_storage_path.name
    _make_non_empty_dir(conflicting_slot)
    _make_non_empty_dir(current_storage_path)

    with pytest.raises(ArchiveRotationError, match="archive destination already exists"):
        rotate_archive("cmems", current_storage_path, archive_root)

    assert conflicting_slot.exists()
    assert current_storage_path.exists()


def _make_non_empty_dir(path: Path, mtime: int | float | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    marker = path / "marker.txt"
    marker.write_text("data", encoding="utf-8")
    if mtime is not None:
        os.utime(marker, (mtime, mtime))
        os.utime(path, (mtime, mtime))


def _slot_dirs(path: Path) -> list[Path]:
    return sorted((child for child in path.iterdir() if child.is_dir()), key=lambda child: child.name)
