"""Data module for AI Trading Bot."""

from importlib import import_module
from typing import Any, Dict, List

_ATTR_TO_MODULE: Dict[str, str] = {
    "HistoricalDataFetcher": ".fetchers",
    "LiveDataFetcher": ".fetchers",
    "TechnicalIndicators": ".indicators",
    "FeatureEngineer": ".preprocessing",
    "MarketSimulator": ".simulator",
    "SimulatedMarketData": ".simulator",
}

__all__ = [
    "HistoricalDataFetcher",
    "LiveDataFetcher",
    "TechnicalIndicators",
    "FeatureEngineer",
    "MarketSimulator",
    "SimulatedMarketData",
    "constants",
]


def __getattr__(name: str) -> Any:
    if name == "constants":
        return import_module(".constants", __name__)

    try:
        module = import_module(_ATTR_TO_MODULE[name], __name__)
    except KeyError as exc:  # pragma: no cover - defensive programming
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    return getattr(module, name)


def __dir__() -> List[str]:
    return sorted(set(__all__ + list(globals().keys())))
