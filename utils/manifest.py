from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
ROOT_KEYS = {"schema_version", "updated_at", "gfs", "cmems"}
GFS_KEYS = {
    "latest_successful_cycle",
    "latest_successful_fetched_at",
    "latest_successful_source_timestamp",
    "storage_root",
    "relative_path",
    "archive_slots",
}
CMEMS_KEYS = {
    "latest_successful_layer_date",
    "latest_successful_fetched_at",
    "latest_successful_source_timestamp",
    "storage_path",
    "archive_slots",
}
ARCHIVE_SLOT_KEYS = {"24h-back", "48h-back"}

GFS_CYCLE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T(00|06|12|18)Z$")
GFS_RELATIVE_PATH_RE = re.compile(r"^gfs/\d{8}/(00z|06z|12z|18z)/$")
CMEMS_LAYER_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CMEMS_STORAGE_PATH_RE = re.compile(r"^storage/cmems/\d{8}/$")


class ManifestCorruptedError(Exception):
    """Raised when ADR-001 §4 manifest content is missing or invalid."""


def read_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "gfs": None,
            "cmems": None,
        }

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ManifestCorruptedError(f"{manifest_path}: invalid JSON ({exc.msg})") from exc
    except OSError as exc:
        raise ManifestCorruptedError(f"{manifest_path}: could not read manifest ({exc})") from exc

    if not isinstance(data, dict):
        raise ManifestCorruptedError(f"{manifest_path}: manifest root must be an object")

    errors = validate_schema(data)
    if errors:
        raise ManifestCorruptedError(f"{manifest_path}: {'; '.join(errors)}")

    return data


def write_manifest(path: str | Path, data: dict[str, Any]) -> None:
    errors = validate_schema(data)
    if errors:
        raise ValueError("; ".join(errors))

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path = Path(path)
    tmp_path = Path(f"{manifest_path}.tmp")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, manifest_path)


def validate_schema(data: dict[str, Any]) -> list[str]:
    """Return ADR-001 §13.1 schema errors; TODO: replace with jsonschema later."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["manifest root must be an object"]

    _validate_required_and_additional(data, ROOT_KEYS, "root", errors)

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append('schema_version must be "1.0"')

    updated_at = data.get("updated_at")
    if not isinstance(updated_at, str) or not _is_utc_iso8601(updated_at):
        errors.append("updated_at must be a UTC ISO 8601 string")

    _validate_gfs(data.get("gfs"), errors)
    _validate_cmems(data.get("cmems"), errors)
    return errors


def _validate_gfs(value: Any, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append("gfs must be an object or null")
        return

    _validate_required_and_additional(value, GFS_KEYS, "gfs", errors)
    _validate_pattern(value.get("latest_successful_cycle"), GFS_CYCLE_RE, "gfs.latest_successful_cycle", errors)
    _validate_utc_field(value.get("latest_successful_fetched_at"), "gfs.latest_successful_fetched_at", errors)
    _validate_nullable_utc_field(
        value.get("latest_successful_source_timestamp"),
        "gfs.latest_successful_source_timestamp",
        errors,
    )
    _validate_str_nonempty(value.get("storage_root"), "gfs.storage_root", errors)
    _validate_pattern(value.get("relative_path"), GFS_RELATIVE_PATH_RE, "gfs.relative_path", errors)
    _validate_archive_slots(value.get("archive_slots"), "gfs.archive_slots", errors)


def _validate_cmems(value: Any, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append("cmems must be an object or null")
        return

    _validate_required_and_additional(value, CMEMS_KEYS, "cmems", errors)
    _validate_pattern(
        value.get("latest_successful_layer_date"),
        CMEMS_LAYER_DATE_RE,
        "cmems.latest_successful_layer_date",
        errors,
    )
    _validate_utc_field(value.get("latest_successful_fetched_at"), "cmems.latest_successful_fetched_at", errors)
    _validate_nullable_utc_field(
        value.get("latest_successful_source_timestamp"),
        "cmems.latest_successful_source_timestamp",
        errors,
    )
    _validate_pattern(value.get("storage_path"), CMEMS_STORAGE_PATH_RE, "cmems.storage_path", errors)
    _validate_archive_slots(value.get("archive_slots"), "cmems.archive_slots", errors)


def _validate_required_and_additional(
    value: dict[str, Any],
    allowed_keys: set[str],
    label: str,
    errors: list[str],
) -> None:
    missing = sorted(allowed_keys - set(value))
    extra = sorted(set(value) - allowed_keys)
    if missing:
        errors.append(f"{label} missing required keys: {', '.join(missing)}")
    if extra:
        errors.append(f"{label} has unexpected keys: {', '.join(extra)}")


def _validate_pattern(value: Any, pattern: re.Pattern[str], label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        errors.append(f"{label} has invalid format")


def _validate_str_nonempty(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")


def _validate_utc_field(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _is_utc_iso8601(value):
        errors.append(f"{label} must be a UTC ISO 8601 string")


def _validate_nullable_utc_field(value: Any, label: str, errors: list[str]) -> None:
    if value is None:
        return
    _validate_utc_field(value, label, errors)


def _validate_archive_slots(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return

    _validate_required_and_additional(value, ARCHIVE_SLOT_KEYS, label, errors)
    for slot_key in sorted(ARCHIVE_SLOT_KEYS):
        slot_value = value.get(slot_key)
        if slot_value is not None and not isinstance(slot_value, dict):
            errors.append(f"{label}.{slot_key} must be an object or null")


def _is_utc_iso8601(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False

    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)
