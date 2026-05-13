from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path


GFS_CYCLE_DIR_RE = re.compile(r"^(00z|06z|12z|18z)$")
DATE_DIR_RE = re.compile(r"^\d{8}$")


class ArchiveRotationError(Exception):
    """Raised when archive layout violates ADR-001 §3.2 invariant."""


def rotate_archive(
    source: str,
    current_storage_path: Path,
    archive_root: Path,
    logger: logging.Logger | None = None,
) -> dict[str, Path | None]:
    """
    Rotate archive slots for a single ingestion source (ADR-001 §3.2).

    Parameters
    ----------
    source : str
        Source identifier, e.g. "gfs" or "cmems". Used only for logging.
    current_storage_path : Path
        Path to the *current* successfully ingested data folder
        (e.g. storage/gfs/20260513/12z/ or storage/cmems/20260513/).
        Must exist and be non-empty when called *before* a new ingest run.
    archive_root : Path
        Root directory under which archive slots are kept
        (e.g. storage/archive/gfs/ or storage/archive/cmems/).
    logger : logging.Logger | None
        Optional logger; defaults to module logger when None.

    Returns
    -------
    dict[str, Path | None]
        {"24h-back": Path | None, "48h-back": Path | None}
        describing slots present *after* successful rotation.

    Raises
    ------
    ArchiveRotationError
        If archive_root contains 3 or more slot directories
        (invariant violation).
    """
    log = logger if logger is not None else logging.getLogger(__name__)
    current_path = Path(current_storage_path)
    archive_path = Path(archive_root)

    _ensure_non_empty_directory(current_path)
    archive_path.mkdir(parents=True, exist_ok=True)

    existing_slots = _list_slot_dirs(archive_path)
    log.info("%s archive before rotation: %d slots", source, len(existing_slots))
    if len(existing_slots) >= 3:
        slot_names = ", ".join(slot.name for slot in existing_slots)
        raise ArchiveRotationError(f"archive invariant violation for {source}: found slots: {slot_names}")

    if len(existing_slots) == 2:
        oldest_slot = existing_slots[0]
        shutil.rmtree(oldest_slot)
        log.info("%s archive removed oldest slot: %s", source, oldest_slot)
        existing_slots = existing_slots[1:]

    destination = archive_path / _slot_name_for_current(current_path)
    if destination.exists():
        raise ArchiveRotationError(f"archive destination already exists for {source}: {destination}")

    shutil.move(str(current_path), str(destination))
    destination.touch(exist_ok=True)
    log.info("%s archive moved current -> archive: %s -> %s", source, current_path, destination)

    after_slots = _list_slot_dirs(archive_path)
    log.info("%s archive after rotation: %d slots", source, len(after_slots))
    if not after_slots:
        raise ArchiveRotationError(f"archive rotation produced no slots for {source}: {archive_path}")

    newest_slot = after_slots[-1]
    older_slot = after_slots[-2] if len(after_slots) >= 2 else None
    return {"24h-back": newest_slot, "48h-back": older_slot}


def _ensure_non_empty_directory(path: Path) -> None:
    if not path.exists():
        raise ArchiveRotationError(f"nothing to rotate: {path} does not exist")
    if not path.is_dir():
        raise ArchiveRotationError(f"nothing to rotate: {path} is not a directory")
    if not any(path.iterdir()):
        raise ArchiveRotationError(f"nothing to rotate: {path} is empty")


def _list_slot_dirs(archive_root: Path) -> list[Path]:
    slots = [path for path in archive_root.iterdir() if path.is_dir()]
    return sorted(slots, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _slot_name_for_current(current_storage_path: Path) -> str:
    if GFS_CYCLE_DIR_RE.fullmatch(current_storage_path.name) and DATE_DIR_RE.fullmatch(current_storage_path.parent.name):
        return f"{current_storage_path.parent.name}_{current_storage_path.name}"
    return current_storage_path.name
