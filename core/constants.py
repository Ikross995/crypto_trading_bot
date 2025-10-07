"""
Core constants for AI Trading Bot.
"""

from enum import Enum


class TradingMode(Enum):
    """Trading execution modes."""
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


class OrderSide(Enum):
    """Order side directions."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class PositionSide(Enum):
    """Position sides for futures trading."""
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"


class SignalType(Enum):
    """Trading signal types."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class ExitReason(Enum):
    """Reasons for position exits."""
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    SIGNAL_REVERSE = "SIGNAL_REVERSE"
    RISK_MANAGEMENT = "RISK_MANAGEMENT"
    MANUAL = "MANUAL"




class OrderStatus(Enum):
    """Order status types."""
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Regime(Enum):
    """Market regime types."""
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    STABLE = "STABLE"


class SignalDirection(Enum):
    """Signal direction types."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    CLOSE = "CLOSE"


class WorkingType(Enum):
    """Order working types for futures trading."""
    MARK_PRICE = "MARK_PRICE"
    CONTRACT_PRICE = "CONTRACT_PRICE"


class TimeInForce(Enum):
    """Order time in force types."""
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate or Cancel  
    FOK = "FOK"  # Fill or Kill
    GTX = "GTX"  # Good Till Crossing


class Timeframe(Enum):
    """Trading timeframe intervals."""
    M1 = "1m"    # 1 minute
    M3 = "3m"    # 3 minutes
    M5 = "5m"    # 5 minutes
    M15 = "15m"  # 15 minutes
    M30 = "30m"  # 30 minutes
    H1 = "1h"    # 1 hour
    H2 = "2h"    # 2 hours
    H4 = "4h"    # 4 hours
    H6 = "6h"    # 6 hours
    H8 = "8h"    # 8 hours
    H12 = "12h"  # 12 hours
    D1 = "1d"    # 1 day
    D3 = "3d"    # 3 days
    W1 = "1w"    # 1 week
    MO1 = "1M"   # 1 month


# Trading utility constants
DEFAULT_LOT_SIZE = 0.001
DEFAULT_TICK_SIZE = 0.01
VALID_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT",
    "XRPUSDT", "DOTUSDT", "UNIUSDT", "LINKUSDT", "LTCUSDT"
]

# Timeframe mappings in milliseconds
TIMEFRAME_MS = {
    '1m': 60 * 1000,
    '3m': 3 * 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '30m': 30 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '2h': 2 * 60 * 60 * 1000,
    '4h': 4 * 60 * 60 * 1000,
    '6h': 6 * 60 * 60 * 1000,
    '8h': 8 * 60 * 60 * 1000,
    '12h': 12 * 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
    '3d': 3 * 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
    '1M': 30 * 24 * 60 * 60 * 1000,
}

# Timeframe mappings in minutes for data fetching
TIMEFRAME_TO_MINUTES = {
    '1m': 1,
    '3m': 3,
    '5m': 5,
    '15m': 15,
    '30m': 30,
    '1h': 60,
    '2h': 120,
    '4h': 240,
    '6h': 360,
    '8h': 480,
    '12h': 720,
    '1d': 1440,      # 24 * 60
    '3d': 4320,      # 3 * 24 * 60  
    '1w': 10080,     # 7 * 24 * 60
    '1M': 43200,     # 30 * 24 * 60
}


# Explicit exports for better compatibility
__all__ = [
    "TradingMode",
    "OrderSide", 
    "OrderType",
    "OrderStatus",
    "PositionSide",
    "SignalType",
    "SignalDirection",
    "ExitReason",
    "Regime",
    "WorkingType",
    "TimeInForce",
    "Timeframe",
    "DEFAULT_LOT_SIZE",
    "DEFAULT_TICK_SIZE",
    "VALID_SYMBOLS",
    "TIMEFRAME_MS",
    "TIMEFRAME_TO_MINUTES",
]