import json

import pytest

from utils.event_logger import EventLoggingError, log_event


def test_log_event_writes_jsonl_line(monkeypatch, tmp_path):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("HYDROMET_INGEST_EVENTS_PATH", str(events_path))

    log_event(
        source="gfs",
        event="poll_attempt",
        target_cycle="2026-05-13T12Z",
        result="not_ready",
        http_status=404,
    )

    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["source"] == "gfs"
    assert payload["event"] == "poll_attempt"
    assert payload["target_cycle"] == "2026-05-13T12Z"
    assert payload["result"] == "not_ready"
    assert payload["http_status"] == 404
    assert "ts" in payload
    assert "latency_ms" not in payload


def test_log_event_includes_extra_fields(monkeypatch, tmp_path):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("HYDROMET_INGEST_EVENTS_PATH", str(events_path))

    log_event(source="gfs", event="poll_attempt", retry_number=3)

    payload = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert payload["retry_number"] == 3


def test_log_event_raises_on_unwritable_path(monkeypatch, tmp_path):
    events_path = tmp_path / "missing" / "events.jsonl"
    monkeypatch.setenv("HYDROMET_INGEST_EVENTS_PATH", str(events_path))

    with pytest.raises(EventLoggingError, match="Could not write ingestion event"):
        log_event(source="gfs", event="poll_attempt")
