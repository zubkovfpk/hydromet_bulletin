from datetime import datetime, timezone

import pytest

from forecast_main import build_output_filename, main


def test_build_output_filename_basic_no_collision(tmp_path):
    output_dir = tmp_path / "out"
    path = build_output_filename(
        start_dt_utc=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
        request_dt_utc=datetime(2026, 5, 13, 9, 15, tzinfo=timezone.utc),
        output_dir=output_dir,
    )

    assert path == output_dir / "Прогноз_20260513_1200.docx"
    assert output_dir.exists()
    assert not path.exists()


def test_build_output_filename_collision_appends_req_suffix(tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "Прогноз_20260513_1200.docx").write_text("existing", encoding="utf-8")

    path = build_output_filename(
        start_dt_utc=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
        request_dt_utc=datetime(2026, 5, 13, 9, 15, tzinfo=timezone.utc),
        output_dir=output_dir,
    )

    assert path == output_dir / "Прогноз_20260513_1200_req-1215.docx"


def test_build_output_filename_double_collision_raises(tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    base = output_dir / "Прогноз_20260513_1200.docx"
    suffixed = output_dir / "Прогноз_20260513_1200_req-1215.docx"
    base.write_text("existing", encoding="utf-8")
    suffixed.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError) as exc_info:
        build_output_filename(
            start_dt_utc=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
            request_dt_utc=datetime(2026, 5, 13, 9, 15, tzinfo=timezone.utc),
            output_dir=output_dir,
        )

    message = str(exc_info.value)
    assert base.name in message
    assert suffixed.name in message


def test_build_output_filename_force_returns_base_path(tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    base = output_dir / "Прогноз_20260513_1200.docx"
    base.write_text("existing", encoding="utf-8")

    path = build_output_filename(
        start_dt_utc=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
        request_dt_utc=datetime(2026, 5, 13, 9, 15, tzinfo=timezone.utc),
        output_dir=output_dir,
        force=True,
    )

    assert path == base


def test_build_output_filename_requires_tz_aware(tmp_path):
    aware = datetime(2026, 5, 13, 9, 15, tzinfo=timezone.utc)
    naive = datetime(2026, 5, 13, 9, 0)

    with pytest.raises(ValueError, match="start_dt_utc must be timezone-aware"):
        build_output_filename(naive, aware, tmp_path)

    with pytest.raises(ValueError, match="request_dt_utc must be timezone-aware"):
        build_output_filename(aware, naive, tmp_path)


def test_build_output_filename_msk_conversion_at_day_boundary(tmp_path):
    path = build_output_filename(
        start_dt_utc=datetime(2026, 5, 13, 23, 30, tzinfo=timezone.utc),
        request_dt_utc=datetime(2026, 5, 13, 23, 45, tzinfo=timezone.utc),
        output_dir=tmp_path,
    )

    assert path.name == "Прогноз_20260514_0230.docx"


def test_forecast_main_dry_run_prints_output_filename(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)

    rc = main(["--date", "2026-05-13", "--time", "18:00", "--tz", "MSK", "--dry-run"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "output_filename:" in captured.out
    assert ".docx" in captured.out
