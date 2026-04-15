"""Lazy exports for utils package.

Avoid eager imports of heavy scientific dependencies when only a submodule
like `utils.downloaders.*` is needed (e.g., fetch_inputs startup path).
"""

from importlib import import_module

__all__ = [
    "wind_statistics",
    "precip_statistics",
    "temp_statistics_morning",
    "temp_statistics_evening",
    "collect_meteo_data",
    "collect_wave_data",
    "create_bulletin_doc",
    "send_bulletin",
]

_SYMBOL_TO_MODULE = {
    "wind_statistics": "utils.wind_statistics",
    "precip_statistics": "utils.precip_statistics",
    "temp_statistics_morning": "utils.temp_statistics",
    "temp_statistics_evening": "utils.temp_statistics",
    "collect_meteo_data": "utils.collect_meteo_data",
    "collect_wave_data": "utils.collect_wave_data",
    "create_bulletin_doc": "utils.doc_builder",
    "send_bulletin": "utils.email_sender",
}


def __getattr__(name: str):
    if name not in _SYMBOL_TO_MODULE:
        raise AttributeError(f"module 'utils' has no attribute {name!r}")
    module = import_module(_SYMBOL_TO_MODULE[name])
    return getattr(module, name)
