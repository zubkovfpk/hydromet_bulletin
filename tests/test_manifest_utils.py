import json
from datetime import datetime, timezone

import pytest

from utils.manifest import ManifestCorruptedError, read_manifest, validate_schema, write_manifest


def test_read_manifest_missing_returns_minimal_structure(tmp_path):
    manifest_path = tmp_path / "manifest.json"

    manifest = read_manifest(manifest_path)

    assert manifest["schema_version"] == "1.0"
    assert manifest["gfs"] is None
    assert manifest["cmems"] is None
    assert _is_utc_iso(manifest["updated_at"])


def test_read_manifest_invalid_json_raises_corrupted(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{not a json", encoding="utf-8")

    with pytest.raises(ManifestCorruptedError, match="invalid JSON"):
        read_manifest(manifest_path)


def test_read_manifest_missing_required_keys_raises_corrupted(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    with pytest.raises(ManifestCorruptedError, match="missing required keys"):
        read_manifest(manifest_path)


def test_validate_schema_accepts_minimal_empty_manifest():
    manifest = {
        "schema_version": "1.0",
        "updated_at": "2026-05-13T12:00:00+00:00",
        "gfs": None,
        "cmems": None,
    }

    assert validate_schema(manifest) == []


def test_validate_schema_accepts_full_gfs_example():
    manifest = {
        "schema_version": "1.0",
        "updated_at": "2026-05-13T12:00:00+00:00",
        "gfs": {
            "latest_successful_cycle": "2026-05-13T12Z",
            "latest_successful_fetched_at": "2026-05-13T16:42:18+00:00",
            "latest_successful_source_timestamp": "2026-05-13T12:00:00+00:00",
            "storage_path": "storage/gfs/20260513/12z/",
            "archive_slots": {
                "24h-back": None,
                "48h-back": None,
            },
        },
        "cmems": None,
    }

    assert validate_schema(manifest) == []


def test_write_manifest_atomic_and_updates_timestamp(tmp_path):
    manifest_path = tmp_path / "storage" / "manifest.json"
    old_timestamp = "2020-01-01T00:00:00+00:00"
    manifest = {
        "schema_version": "1.0",
        "updated_at": old_timestamp,
        "gfs": None,
        "cmems": None,
    }

    write_manifest(manifest_path, manifest)

    stored = read_manifest(manifest_path)
    assert manifest_path.exists()
    assert not (tmp_path / "storage" / "manifest.json.tmp").exists()
    assert stored["updated_at"] != old_timestamp
    assert _parse_utc(stored["updated_at"]) > _parse_utc(old_timestamp)


def test_write_manifest_rejects_invalid_data(tmp_path):
    manifest = {
        "schema_version": "0.9",
        "updated_at": "2026-05-13T12:00:00+00:00",
        "gfs": None,
        "cmems": None,
    }

    with pytest.raises(ValueError, match='schema_version must be "1.0"'):
        write_manifest(tmp_path / "manifest.json", manifest)


def _is_utc_iso(value: str) -> bool:
    return _parse_utc(value).tzinfo is not None


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    return parsed
