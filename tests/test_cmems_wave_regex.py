import re

import pytest

from utils.downloaders.cmems_downloader import build_cmems_wave_regex


def test_build_cmems_wave_regex_length_run12h_first2026042200():
    rgx = build_cmems_wave_regex("20260421", "12", "2026042200", forecast_days=5)
    expected = [
        "mfwamglocep_2026042200_R20260421_12H.nc",
        "mfwamglocep_2026042212_R20260421_12H.nc",
        "mfwamglocep_2026042300_R20260421_12H.nc",
        "mfwamglocep_2026042312_R20260421_12H.nc",
        "mfwamglocep_2026042400_R20260421_12H.nc",
        "mfwamglocep_2026042412_R20260421_12H.nc",
        "mfwamglocep_2026042500_R20260421_12H.nc",
        "mfwamglocep_2026042512_R20260421_12H.nc",
        "mfwamglocep_2026042600_R20260421_12H.nc",
        "mfwamglocep_2026042612_R20260421_12H.nc",
    ]
    hits = [n for n in expected if re.match(rgx, f"/any/dir/{n}")]
    assert len(hits) == 10


def test_build_cmems_wave_regex_length_run00h_first2026042112():
    rgx = build_cmems_wave_regex("20260421", "00", "2026042112", forecast_days=5)
    expected = [
        "mfwamglocep_2026042112_R20260421_00H.nc",
        "mfwamglocep_2026042200_R20260421_00H.nc",
        "mfwamglocep_2026042212_R20260421_00H.nc",
        "mfwamglocep_2026042300_R20260421_00H.nc",
        "mfwamglocep_2026042312_R20260421_00H.nc",
        "mfwamglocep_2026042400_R20260421_00H.nc",
        "mfwamglocep_2026042412_R20260421_00H.nc",
        "mfwamglocep_2026042500_R20260421_00H.nc",
        "mfwamglocep_2026042512_R20260421_00H.nc",
        "mfwamglocep_2026042600_R20260421_00H.nc",
    ]
    hits = [n for n in expected if re.match(rgx, f"/any/dir/{n}")]
    assert len(hits) == 10


def test_build_cmems_wave_regex_rejects_wrong_run_hour():
    with pytest.raises(ValueError, match="run_hour"):
        build_cmems_wave_regex("20260421", "24", "2026042200", forecast_days=5)


def test_build_cmems_wave_regex_rejects_misaligned_first_forecast_dt():
    with pytest.raises(ValueError, match="first_forecast_dt"):
        build_cmems_wave_regex("20260421", "12", "2026042203", forecast_days=5)


def test_build_cmems_wave_regex_rejects_nonpositive_forecast_days():
    with pytest.raises(ValueError, match="forecast_days"):
        build_cmems_wave_regex("20260421", "12", "2026042200", forecast_days=0)


def test_build_cmems_wave_regex_hour_suffix_is_strict():
    rgx_12 = build_cmems_wave_regex("20260421", "12", "2026042200", forecast_days=5)
    wrong_suffix = "/any/dir/mfwamglocep_2026042200_R20260421_00H.nc"
    assert re.match(rgx_12, wrong_suffix) is None

    rgx_00 = build_cmems_wave_regex("20260421", "00", "2026042112", forecast_days=5)
    wrong_suffix_12 = "/any/dir/mfwamglocep_2026042112_R20260421_12H.nc"
    assert re.match(rgx_00, wrong_suffix_12) is None


def test_build_cmems_wave_regex_varying_forecast_days():
    rgx = build_cmems_wave_regex("20260421", "00", "2026042112", forecast_days=3)
    expected = [
        "mfwamglocep_2026042112_R20260421_00H.nc",
        "mfwamglocep_2026042200_R20260421_00H.nc",
        "mfwamglocep_2026042212_R20260421_00H.nc",
        "mfwamglocep_2026042300_R20260421_00H.nc",
        "mfwamglocep_2026042312_R20260421_00H.nc",
        "mfwamglocep_2026042400_R20260421_00H.nc",
    ]
    hits = [n for n in expected if re.match(rgx, f"/x/{n}")]
    assert len(hits) == 6


def test_build_cmems_wave_regex_rejects_wrong_run_date_in_filename():
    rgx = build_cmems_wave_regex("20260421", "00", "2026042112", forecast_days=5)
    wrong = "/any/dir/mfwamglocep_2026042112_R20260420_00H.nc"
    assert re.match(rgx, wrong) is None
