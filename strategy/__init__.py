"""
Trading strategy module for AI Trading Bot.

Provides signal generation, risk management, DCA logic, and exit strategies.
"""

from .signals import SignalGenerator
from .risk import RiskManager
from .exits import ExitManager
from .dca import DCAManager

__all__ = [
    "SignalGenerator",
    "RiskManager", 
    "ExitManager",
    "DCAManager"
]