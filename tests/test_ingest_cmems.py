"""Tests for ingest_cmems.py"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import ingest_cmems


def test_resolve_cmems_run_params_morning():
    """При current_utc.hour < 12 → run_hour="12", run_date=yesterday."""
    snapshot = date(2026, 6, 8)
    
    # Мокаем datetime.now для 08:00 UTC
    with patch("ingest_cmems.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc)
        mock_dt.timedelta = timedelta
        
        run_date_str, run_hour, first_forecast_dt = ingest_cmems._resolve_cmems_run_params(snapshot)
    
    assert run_hour == "12"
    assert run_date_str == "2026-06-07"  # yesterday
    assert first_forecast_dt == "2026060712"


def test_resolve_cmems_run_params_afternoon():
    """При current_utc.hour >= 12 → run_hour="00", run_date=today."""
    snapshot = date(2026, 6, 8)
    
    # Мокаем datetime.now для 14:00 UTC
    with patch("ingest_cmems.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc)
        mock_dt.timedelta = timedelta
        
        run_date_str, run_hour, first_forecast_dt = ingest_cmems._resolve_cmems_run_params(snapshot)
    
    assert run_hour == "00"
    assert run_date_str == "2026-06-08"  # today
    assert first_forecast_dt == "2026060800"


def test_dry_run_returns_zero():
    """--dry-run не вызывает CMEMSDownloader.download, возвращает 0."""
    with patch("ingest_cmems.CMEMSDownloader") as mock_downloader_class:
        cfg = MagicMock()
        logger = MagicMock()
        snapshot = date(2026, 6, 8)
        
        result = ingest_cmems.run_ingest(snapshot, dry_run=True, cfg=cfg, logger=logger)
        
        # CMEMSDownloader не должен быть вызван
        mock_downloader_class.assert_not_called()
        assert result == 0


def test_run_ingest_writes_manifest_on_success():
    """mock CMEMSDownloader.download → True, проверить что manifest.cmems обновлён."""
    with patch("ingest_cmems.CMEMSDownloader") as mock_downloader_class:
        with patch("ingest_cmems.read_manifest") as mock_read:
            with patch("ingest_cmems.write_manifest") as mock_write:
                # Setup mocks
                mock_read.return_value = {"schema_version": "1.0"}
                mock_downloader = MagicMock()
                mock_downloader.download.return_value = True
                mock_downloader_class.return_value = mock_downloader
                
                # Mock config
                cfg = MagicMock()
                cfg.get.return_value = "data/storage/cmems"
                
                logger = MagicMock()
                snapshot = date(2026, 6, 8)
                
                # Patch datetime for consistent test
                with patch("ingest_cmems.datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc)
                    mock_dt.timedelta = timedelta
                    mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
                    
                    result = ingest_cmems.run_ingest(snapshot, dry_run=False, cfg=cfg, logger=logger)
                
                # Проверяем что manifest записан
                assert result == 0
                mock_write.assert_called_once()
                
                # Проверяем структуру CMEMS блока
                call_args = mock_write.call_args
                manifest = call_args[0][1]
                assert "cmems" in manifest
                assert manifest["cmems"]["latest_successful_layer_date"] == "2026-06-08"
                assert manifest["cmems"]["storage_path"] is not None

