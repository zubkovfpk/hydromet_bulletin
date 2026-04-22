"""Smoke: *_statistics symbols used by forecast runners are functions, not modules."""


def test_statistics_functions_are_callable():
    from utils.precip_statistics import precip_statistics
    from utils.temp_statistics import temp_statistics_evening, temp_statistics_morning
    from utils.wind_statistics import wind_statistics

    assert callable(wind_statistics)
    assert callable(precip_statistics)
    assert callable(temp_statistics_morning)
    assert callable(temp_statistics_evening)


def test_forecast_runner_modules_import():
    import forecast_evening  # noqa: F401
    import forecast_morning  # noqa: F401

    assert callable(forecast_morning.run_morning)
    assert callable(forecast_evening.run_evening)
