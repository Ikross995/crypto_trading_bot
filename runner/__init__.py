
# Apply compatibility patches before importing runners
try:
    import compat_complete as compat
    compat.apply()
except ImportError:
    try:
        import compat
        compat.apply()
    except ImportError:
        pass  # Continue without compat patches

"""
Trading Bot Runner Module.

Contains execution engines for live trading, paper trading, and backtesting.
"""

from .live import LiveTradingEngine
from .paper import PaperTradingEngine  
from .backtest import BacktestEngine

__all__ = [
    "LiveTradingEngine",
    "PaperTradingEngine", 
    "BacktestEngine",
]