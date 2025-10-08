"""Data module for AI Trading Bot.

The package previously imported a large number of submodules during import
time.  That behaviour created circular import issues once the market data
simulator started being used by the exchange client: ``exchange.client``
imports ``data.simulator`` which, by virtue of the old eager imports here,
pulled ``data.fetchers``; the fetchers depend on ``exchange.client`` and the
cycle exploded before the simulator could even be constructed.

To avoid the cycle we now lazily expose the commonly used objects.  Runtime
consumers continue to access ``data.HistoricalDataFetcher`` (and friends)
exactly the same way, but the actual modules are imported only when the
attribute is accessed for the first time.  This keeps the package initialisation
lightweight and makes the simulator safe to use from the exchange layer.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .fetchers import HistoricalDataFetcher, LiveDataFetcher
    from .indicators import TechnicalIndicators
    from .preprocessing import FeatureEngineer
    from .simulator import MarketSimulator, SimulatedMarketData

# Compatibility import (deprecated - use core.constants instead)
try:  # pragma: no cover - optional dependency path for legacy modules
    from . import constants  # type: ignore
except ImportError:  # pragma: no cover
    constants = None

__all__ = [
    "HistoricalDataFetcher",
    "LiveDataFetcher",
    "TechnicalIndicators",
    "FeatureEngineer",
    "MarketSimulator",
    "SimulatedMarketData",
]


_ATTR_TO_MODULE = {
    "HistoricalDataFetcher": "data.fetchers",
    "LiveDataFetcher": "data.fetchers",
    "TechnicalIndicators": "data.indicators",
    "FeatureEngineer": "data.preprocessing",
    "MarketSimulator": "data.simulator",
    "SimulatedMarketData": "data.simulator",
}


def __getattr__(name: str) -> Any:
    module_name = _ATTR_TO_MODULE.get(name)
    if not module_name:  # pragma: no cover - maintain normal AttributeError
        raise AttributeError(f"module 'data' has no attribute {name!r}")
    module = import_module(module_name)
    return getattr(module, name)


def __dir__() -> list[str]:  # pragma: no cover - cosmetic only
    return sorted(set(globals()) | set(__all__))
