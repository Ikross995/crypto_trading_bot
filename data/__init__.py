"""
Data module for AI Trading Bot.

Handles historical data fetching, live market data, technical indicators,
and feature engineering for ML models.
"""

from .fetchers import HistoricalDataFetcher, LiveDataFetcher
from .indicators import TechnicalIndicators
from .preprocessing import FeatureEngineer

# Compatibility import (deprecated - use core.constants instead)
try:
    from . import constants
except ImportError:
    constants = None

__all__ = [
    "HistoricalDataFetcher",
    "LiveDataFetcher", 
    "TechnicalIndicators",
    "FeatureEngineer"
]