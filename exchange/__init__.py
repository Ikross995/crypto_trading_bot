"""
Exchange module for AI Trading Bot.

Handles all Binance UM Futures interactions including REST API, WebSocket feeds,
order management, position tracking, and market data.
"""

from .client import BinanceClient, create_client
from .orders import OrderManager
from .positions import PositionManager
from .market_data import MarketDataProvider
from .websockets import WebSocketManager

__all__ = [
    "BinanceClient",
    "create_client",
    "OrderManager", 
    "PositionManager",
    "MarketDataProvider",
    "WebSocketManager",
]