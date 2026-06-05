from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email import message_from_string

import pytest

from utils import email_sender


def test_attachment_content_disposition_includes_cyrillic_filename(monkeypatch, tmp_path):
    docx_path = tmp_path / "Прогноз_20260514_1800.docx"
    docx_path.write_bytes(b"fake-docx")
    sent_payloads: list[str] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def login(self, *args, **kwargs) -> None:
            return None

        def sendmail(self, _from: str, _to: list[str], payload: str) -> None:
            sent_payloads.append(payload)

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    ok = email_sender.send_bulletin(
        docx_path=str(docx_path),
        recipient="user@example.com",
        smtp_host="smtp.example.com",
        smtp_port=465,
        login="sender@example.com",
        password="secret",
        bulletin_type="on-demand",
        run_date=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )

    assert ok is True
    assert len(sent_payloads) == 1

    msg = message_from_string(sent_payloads[0])
    attachment = msg.get_payload()[1]
    content_disposition = attachment.get("Content-Disposition", "")

    lowered = content_disposition.lower()
    assert "filename" in lowered
    assert (
        "Прогноз" in content_disposition
        or "=?utf-8?" in lowered
        or ("filename*=" in lowered and "20260514_1800.docx" in content_disposition)
    )


def test_send_bulletin_missing_file_returns_false(tmp_path):
    ok = email_sender.send_bulletin(
        docx_path=str(tmp_path / "missing.docx"),
        recipient="user@example.com",
        smtp_host="smtp.example.com",
        smtp_port=465,
        login="sender@example.com",
        password="secret",
    )

    assert ok is False
