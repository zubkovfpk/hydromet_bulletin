from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_forecast_morning_has_deprecation_warning():
    source = (REPO_ROOT / "forecast_morning.py").read_text(encoding="utf-8")

    assert "import warnings" in source
    assert "warnings.warn(" in source
    assert "forecast_morning.py is deprecated" in source
    assert "DeprecationWarning" in source
    assert "ADR-001" in source


def test_forecast_evening_has_deprecation_warning():
    source = (REPO_ROOT / "forecast_evening.py").read_text(encoding="utf-8")

    assert "import warnings" in source
    assert "warnings.warn(" in source
    assert "forecast_evening.py is deprecated" in source
    assert "DeprecationWarning" in source
    assert "ADR-001" in source
