from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

import forecast_main
from utils.manifest import ManifestCorruptedError
from utils.validate_outputs import ValidationError


def test_real_run_calls_send_bulletin_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "config.ini")
    _patch_pipeline(monkeypatch)
    send_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        forecast_main,
        "email_sender",
        SimpleNamespace(send_bulletin=lambda **kwargs: send_calls.append(kwargs) or True),
    )

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK"])

    assert exit_code == 0
    assert len(send_calls) == 1
    assert Path(send_calls[0]["docx_path"]).exists()
    assert send_calls[0]["docx_path"].endswith(".docx")


def test_no_email_skips_send_bulletin(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    send_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        forecast_main,
        "email_sender",
        SimpleNamespace(send_bulletin=lambda **kwargs: send_calls.append(kwargs) or True),
    )
    caplog.set_level(logging.INFO)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--no-email"])

    assert exit_code == 0
    assert send_calls == []
    assert "email skipped (--no-email)" in caplog.text


def test_dry_run_never_sends_email(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    send_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        forecast_main,
        "email_sender",
        SimpleNamespace(send_bulletin=lambda **kwargs: send_calls.append(kwargs) or True),
    )

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert send_calls == []
    assert not list((tmp_path / "output").glob("*.docx"))
    assert "[dry-run] pipeline plan:" in captured.out


def test_email_delivery_failure_returns_3(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "config.ini")
    _patch_pipeline(monkeypatch)

    def fail_send_bulletin(**kwargs: Any) -> bool:
        raise OSError("smtp refused")

    monkeypatch.setattr(forecast_main, "email_sender", SimpleNamespace(send_bulletin=fail_send_bulletin))
    caplog.set_level(logging.ERROR)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK"])

    assert exit_code == 3
    assert "email delivery failed" in caplog.text


def test_validation_error_returns_1(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "config.ini")
    _patch_pipeline(monkeypatch, validation_error=ValidationError("bad shape"))
    send_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        forecast_main,
        "email_sender",
        SimpleNamespace(send_bulletin=lambda **kwargs: send_calls.append(kwargs) or True),
    )

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK"])

    assert exit_code == 1
    assert send_calls == []


def test_ingestion_missing_filenotfound_returns_2(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "config.ini")
    _patch_pipeline(monkeypatch, meteo_error=FileNotFoundError("no nc"))
    send_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        forecast_main,
        "email_sender",
        SimpleNamespace(send_bulletin=lambda **kwargs: send_calls.append(kwargs) or True),
    )
    caplog.set_level(logging.ERROR)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK"])

    assert exit_code == 2
    assert send_calls == []
    assert "ingestion missing" in caplog.text


def test_manifest_corrupted_returns_2(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(forecast_main, "read_manifest", lambda path: (_ for _ in ()).throw(ManifestCorruptedError("bad json")))

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK"])

    assert exit_code == 2


def test_internal_error_returns_10(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "config.ini")
    _patch_pipeline(monkeypatch, doc_error=RuntimeError("boom"))
    caplog.set_level(logging.ERROR)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK"])

    assert exit_code == 10
    assert "internal error" in caplog.text
    assert "RuntimeError: boom" in caplog.text or "boom" in caplog.text


def test_email_smtp_settings_taken_from_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "config.ini")
    _patch_pipeline(monkeypatch)
    send_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        forecast_main,
        "email_sender",
        SimpleNamespace(send_bulletin=lambda **kwargs: send_calls.append(kwargs) or True),
    )

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK"])
    source = (Path(__file__).resolve().parents[1] / "forecast_main.py").read_text(encoding="utf-8")

    assert exit_code == 0
    assert send_calls[0]["recipient"] == "ops-list"
    assert send_calls[0]["smtp_host"] == "smtp-host-from-config"
    assert send_calls[0]["smtp_port"] == 465
    assert send_calls[0]["login"] == "smtp-login-from-config"
    assert re.search(r"\b\S+@\S+\.\S+\b", source) is None


def _patch_pipeline(
    monkeypatch,
    *,
    meteo_error: Exception | None = None,
    validation_error: Exception | None = None,
    doc_error: Exception | None = None,
) -> None:
    def fake_collect_meteo_data(*args: Any, **kwargs: Any) -> dict[str, np.ndarray]:
        if meteo_error is not None:
            raise meteo_error
        return _fake_meteo()

    def fake_collect_wave_data(*args: Any, **kwargs: Any) -> tuple[np.ndarray, datetime, datetime]:
        start = datetime(2026, 5, 14, tzinfo=timezone.utc)
        return np.ones((2, 2, 1)), start, start

    def fake_assert_valid_for_bulletin(*args: Any, **kwargs: Any) -> None:
        if validation_error is not None:
            raise validation_error

    def fake_build_doc(*args: Any, **kwargs: Any) -> str:
        if doc_error is not None:
            raise doc_error
        output_path = Path(kwargs["output_path"])
        output_path.write_bytes(b"\x00")
        return str(output_path)

    monkeypatch.setattr(forecast_main, "_poll_until_ready", lambda **kwargs: None)
    monkeypatch.setattr(forecast_main, "collect_meteo_data", fake_collect_meteo_data)
    monkeypatch.setattr(forecast_main, "collect_wave_data", fake_collect_wave_data)
    monkeypatch.setattr(forecast_main, "assert_valid_for_bulletin", fake_assert_valid_for_bulletin)
    monkeypatch.setattr(forecast_main, "wind_statistics", lambda *args, **kwargs: ("северный", 1.0, 2.0))
    monkeypatch.setattr(forecast_main, "precip_statistics", lambda *args, **kwargs: "Без осадков.")
    monkeypatch.setattr(forecast_main, "temp_statistics", lambda *args, **kwargs: "Температура воздуха 10...12 °С.")
    monkeypatch.setattr(forecast_main, "build_doc", fake_build_doc)


def _fake_meteo() -> dict[str, np.ndarray]:
    daily = np.ones((2, 2, 1))
    return {
        "Temp": np.ones((2, 2, 2)) * 10.0,
        "Rain": daily,
        "Freeze_Rain": daily,
        "Ice_Pell": daily,
        "Snow": daily,
        "Wind_Gust": daily * 5.0,
        "U_wind": daily,
        "V_wind": daily,
        "Vis": daily * 10_000.0,
    }


def _write_config(path: Path) -> None:
    path.write_text(
        """
[Email]
recipient = ops-list
smtp_host = smtp-host-from-config
smtp_port = 465
login = smtp-login-from-config
password = smtp-password-from-config
""".strip(),
        encoding="utf-8",
    )
