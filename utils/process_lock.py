from __future__ import annotations

import errno
import importlib
import os
import sys
from types import TracebackType
from typing import TextIO

from utils import event_logger


class ProcessLock:
    """Cross-platform non-blocking process lock for ADR-001 §9.2 ingest runners."""

    def __init__(self, lock_path: str) -> None:
        self.lock_path = lock_path
        self._file: TextIO | None = None

    def __enter__(self) -> "ProcessLock":
        lock_file = open(self.lock_path, "a+", encoding="utf-8")
        self._ensure_lock_byte(lock_file)

        try:
            acquired = self._acquire(lock_file)
        except Exception:
            lock_file.close()
            raise

        if not acquired:
            lock_file.close()
            event_logger.log_event(source="gfs", event="lock_contention", result="skipped")
            sys.exit(0)
            raise SystemExit(0)

        self._file = lock_file
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._file is None:
            return

        try:
            self._release(self._file)
        finally:
            self._file.close()
            self._file = None

    @staticmethod
    def _ensure_lock_byte(lock_file: TextIO) -> None:
        if os.name != "nt":
            return

        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write("\0")
            lock_file.flush()
        lock_file.seek(0)

    @staticmethod
    def _acquire(lock_file: TextIO) -> bool:
        lock_file.seek(0)
        if os.name == "nt":
            msvcrt = importlib.import_module("msvcrt")
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    return False
                raise
            return True

        fcntl = importlib.import_module("fcntl")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        return True

    @staticmethod
    def _release(lock_file: TextIO) -> None:
        lock_file.seek(0)
        if os.name == "nt":
            msvcrt = importlib.import_module("msvcrt")
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            return

        fcntl = importlib.import_module("fcntl")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
