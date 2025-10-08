"""Data module for AI Trading Bot."""

from .fetchers import HistoricalDataFetcher, LiveDataFetcher
from .indicators import TechnicalIndicators
from .preprocessing import FeatureEngineer
from .simulator import MarketSimulator, SimulatedMarketData

# Compatibility import (deprecated - use core.constants instead)
try:
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
