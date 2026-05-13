from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_EVENTS_PATH = Path("/var/lib/hydromet/ingest_events/ingest_events.jsonl")
EVENTS_PATH_ENV = "HYDROMET_INGEST_EVENTS_PATH"


class EventLoggingError(Exception):
    """Raised when ADR-001 §7 ingestion event logging cannot be persisted."""


def _events_path() -> Path:
    return Path(os.environ.get(EVENTS_PATH_ENV, str(DEFAULT_EVENTS_PATH)))


def log_event(
    source: str,
    event: str,
    *,
    target_cycle: str | None = None,
    target_date: str | None = None,
    result: str | None = None,
    http_status: int | None = None,
    latency_ms: int | None = None,
    source_timestamp: str | None = None,
    bytes_downloaded: int | None = None,
    duration_ms: int | None = None,
    user_ip_region: str | None = None,
    **extra: Any,
) -> None:
    """Append one durable JSONL event for ADR-001 §7 ingestion telemetry."""
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "event": event,
    }

    optional_fields: dict[str, Any] = {
        "target_cycle": target_cycle,
        "target_date": target_date,
        "result": result,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "source_timestamp": source_timestamp,
        "bytes_downloaded": bytes_downloaded,
        "duration_ms": duration_ms,
        "user_ip_region": user_ip_region,
    }
    payload.update({key: value for key, value in optional_fields.items() if value is not None})
    payload.update(extra)

    path = _events_path()
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise EventLoggingError(f"Could not write ingestion event to {path}: {exc}") from exc
