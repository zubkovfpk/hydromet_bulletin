import importlib
import logging
import os
import sys
from typing import Any, TextIO

import pytest

import utils.process_lock as process_lock
from utils.process_lock import ProcessLock


def test_process_lock_allows_single_entry(tmp_path):
    lock_path = tmp_path / ".lock"

    with ProcessLock(str(lock_path)):
        assert lock_path.exists()


def test_process_lock_releases_on_exit(tmp_path):
    lock_path = tmp_path / ".lock"

    with ProcessLock(str(lock_path)):
        pass

    with ProcessLock(str(lock_path)):
        assert lock_path.exists()


def test_process_lock_contention_calls_log_and_exits(monkeypatch, tmp_path):
    lock_path = tmp_path / ".lock"
    holder = open(lock_path, "a+", encoding="utf-8")
    _ensure_lock_byte(holder)
    _acquire_manual_lock(holder)

    log_calls: list[dict[str, Any]] = []
    exit_codes: list[int | None] = []

    def fake_log_event(**kwargs: Any) -> None:
        log_calls.append(kwargs)

    def fake_exit(code: int | None = 0) -> None:
        exit_codes.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(process_lock, "log_event", fake_log_event)
    monkeypatch.setattr(sys, "exit", fake_exit)

    try:
        with pytest.raises(SystemExit) as exc_info:
            ProcessLock(str(lock_path)).__enter__()
    finally:
        _release_manual_lock(holder)
        holder.close()

    assert exc_info.value.code == 0
    assert exit_codes == [0]
    assert log_calls == [{"source": "gfs", "event": "lock_contention", "result": "skipped"}]


def test_lock_contention_safe_when_log_event_fails(monkeypatch, tmp_path, caplog):
    lock_path = tmp_path / ".lock"
    holder = open(lock_path, "a+", encoding="utf-8")
    _ensure_lock_byte(holder)
    _acquire_manual_lock(holder)

    exit_codes: list[int | None] = []

    def fail_log_event(**kwargs: Any) -> None:
        raise RuntimeError("event log not writable")

    def fake_exit(code: int | None = 0) -> None:
        exit_codes.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(process_lock, "log_event", fail_log_event)
    monkeypatch.setattr(sys, "exit", fake_exit)
    caplog.set_level(logging.WARNING, logger="utils.process_lock")

    try:
        with pytest.raises(SystemExit) as exc_info:
            ProcessLock(str(lock_path)).__enter__()
    finally:
        _release_manual_lock(holder)
        holder.close()

    assert exc_info.value.code == 0
    assert exit_codes == [0]
    assert "failed to log lock_contention event" in caplog.text


def _ensure_lock_byte(lock_file: TextIO) -> None:
    if os.name != "nt":
        return

    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write("\0")
        lock_file.flush()
    lock_file.seek(0)


def _acquire_manual_lock(lock_file: TextIO) -> None:
    lock_file.seek(0)
    if os.name == "nt":
        msvcrt = importlib.import_module("msvcrt")
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    fcntl = importlib.import_module("fcntl")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_manual_lock(lock_file: TextIO) -> None:
    lock_file.seek(0)
    if os.name == "nt":
        msvcrt = importlib.import_module("msvcrt")
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl = importlib.import_module("fcntl")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
