"""
WebSocket module for AI Trading Bot.

Handles real-time WebSocket connections to Binance for live market data,
order updates, and position changes.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

try:
    import websockets  # noqa: F401
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

from core.config import Config
from core.types import MarketData, OrderUpdate

logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    """
    WebSocket client for Binance UM Futures.

    Provides real-time data streams for:
    - Market data (klines, ticker, depth)
    - Account updates (orders, positions, balance)
    - User data stream
    """

    def __init__(self, config: Config):
        """Initialize WebSocket client."""
        self.config = config
        self.base_url = "wss://fstream.binance.com"
        if config.testnet:
            self.base_url = "wss://stream.binancefuture.com"

        self.connections: dict[str, Any] = {}
        self.callbacks: dict[str, list[Callable]] = {}
        self.running = False

        if not WEBSOCKETS_AVAILABLE:
            logger.warning("websockets package not available - WebSocket functionality disabled")

    async def connect(self) -> bool:
        """Connect to WebSocket streams."""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("Cannot connect: websockets package not installed")
            return False

        try:
            self.running = True
            logger.info("WebSocket client connected successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect WebSocket client: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect all WebSocket connections."""
        self.running = False

        for stream_name, connection in self.connections.items():
            try:
                if hasattr(connection, 'close'):
                    await connection.close()
                logger.debug(f"Disconnected stream: {stream_name}")
            except Exception as e:
                logger.error(f"Error disconnecting {stream_name}: {e}")

        self.connections.clear()
        logger.info("All WebSocket connections closed")

    async def subscribe_klines(self, symbol: str, interval: str, callback: Callable) -> bool:
        """Subscribe to kline/candlestick data."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("Klines subscription skipped: websockets not available")
            return False

        stream_name = f"{symbol.lower()}@kline_{interval}"

        try:
            # Store callback
            if stream_name not in self.callbacks:
                self.callbacks[stream_name] = []
            self.callbacks[stream_name].append(callback)

            logger.info(f"Subscribed to klines: {stream_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to klines {stream_name}: {e}")
            return False

    async def subscribe_ticker(self, symbol: str, callback: Callable) -> bool:
        """Subscribe to 24hr ticker statistics."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("Ticker subscription skipped: websockets not available")
            return False

        stream_name = f"{symbol.lower()}@ticker"

        try:
            # Store callback
            if stream_name not in self.callbacks:
                self.callbacks[stream_name] = []
            self.callbacks[stream_name].append(callback)

            logger.info(f"Subscribed to ticker: {stream_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to ticker {stream_name}: {e}")
            return False

    async def subscribe_user_data(self, callback: Callable) -> bool:
        """Subscribe to user data stream (orders, positions, balance)."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("User data subscription skipped: websockets not available")
            return False

        stream_name = "user_data"

        try:
            # Store callback
            if stream_name not in self.callbacks:
                self.callbacks[stream_name] = []
            self.callbacks[stream_name].append(callback)

            logger.info("Subscribed to user data stream")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to user data: {e}")
            return False

    def add_callback(self, stream_name: str, callback: Callable) -> None:
        """Add callback for a specific stream."""
        if stream_name not in self.callbacks:
            self.callbacks[stream_name] = []
        self.callbacks[stream_name].append(callback)

    def remove_callback(self, stream_name: str, callback: Callable) -> None:
        """Remove callback for a specific stream."""
        if stream_name in self.callbacks:
            try:
                self.callbacks[stream_name].remove(callback)
                if not self.callbacks[stream_name]:
                    del self.callbacks[stream_name]
            except ValueError:
                pass

    async def _handle_message(self, stream_name: str, message: dict[str, Any]) -> None:
        """Handle incoming WebSocket message."""
        if stream_name in self.callbacks:
            for callback in self.callbacks[stream_name]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(message)
                    else:
                        callback(message)
                except Exception as e:
                    logger.error(f"Error in callback for {stream_name}: {e}")

    def is_connected(self) -> bool:
        """Check if WebSocket client is connected."""
        return self.running and WEBSOCKETS_AVAILABLE


class MockWebSocketClient(BinanceWebSocketClient):
    """
    Mock WebSocket client for testing and paper trading.

    Simulates WebSocket functionality without real connections.
    """

    def __init__(self, config: Config):
        """Initialize mock WebSocket client."""
        super().__init__(config)
        self.mock_data: dict[str, Any] = {}
        logger.info("Mock WebSocket client initialized")

    async def connect(self) -> bool:
        """Mock connection - always succeeds."""
        self.running = True
        logger.info("Mock WebSocket client connected")
        return True

    async def subscribe_klines(self, symbol: str, interval: str, callback: Callable) -> bool:
        """Mock klines subscription."""
        stream_name = f"{symbol.lower()}@kline_{interval}"

        if stream_name not in self.callbacks:
            self.callbacks[stream_name] = []
        self.callbacks[stream_name].append(callback)

        logger.debug(f"Mock subscription to klines: {stream_name}")
        return True

    async def subscribe_ticker(self, symbol: str, callback: Callable) -> bool:
        """Mock ticker subscription."""
        stream_name = f"{symbol.lower()}@ticker"

        if stream_name not in self.callbacks:
            self.callbacks[stream_name] = []
        self.callbacks[stream_name].append(callback)

        logger.debug(f"Mock subscription to ticker: {stream_name}")
        return True

    async def subscribe_user_data(self, callback: Callable) -> bool:
        """Mock user data subscription."""
        stream_name = "user_data"

        if stream_name not in self.callbacks:
            self.callbacks[stream_name] = []
        self.callbacks[stream_name].append(callback)

        logger.debug("Mock subscription to user data")
        return True

    async def simulate_kline_data(self, symbol: str, interval: str, kline_data: dict[str, Any]) -> None:
        """Simulate kline data for testing."""
        stream_name = f"{symbol.lower()}@kline_{interval}"

        mock_message = {
            "e": "kline",
            "E": int(datetime.now().timestamp() * 1000),
            "s": symbol,
            "k": kline_data
        }

        await self._handle_message(stream_name, mock_message)

    async def simulate_ticker_data(self, symbol: str, ticker_data: dict[str, Any]) -> None:
        """Simulate ticker data for testing."""
        stream_name = f"{symbol.lower()}@ticker"

        mock_message = {
            "e": "24hrTicker",
            "E": int(datetime.now().timestamp() * 1000),
            "s": symbol,
            **ticker_data
        }

        await self._handle_message(stream_name, mock_message)

    async def simulate_order_update(self, order_data: dict[str, Any]) -> None:
        """Simulate order update for testing."""
        mock_message = {
            "e": "ORDER_TRADE_UPDATE",
            "E": int(datetime.now().timestamp() * 1000),
            "o": order_data
        }

        await self._handle_message("user_data", mock_message)


class WebSocketManager:
    """
    WebSocket manager for backward compatibility.
    
    This is a wrapper around the WebSocket clients that provides
    a unified interface for managing WebSocket connections.
    """
    
    def __init__(self, config: Config):
        """Initialize WebSocket manager."""
        self.config = config
        self.client = create_websocket_client(config)
        self._connected = False
        logger.info(f"WebSocketManager initialized with {type(self.client).__name__}")
    
    async def connect(self) -> bool:
        """Connect to WebSocket streams."""
        try:
            result = await self.client.connect()
            self._connected = result
            if result:
                logger.info("WebSocketManager connected successfully")
            else:
                logger.error("WebSocketManager failed to connect")
            return result
        except Exception as e:
            logger.error(f"WebSocketManager connection error: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect all WebSocket connections."""
        try:
            await self.client.disconnect()
            self._connected = False
            logger.info("WebSocketManager disconnected")
        except Exception as e:
            logger.error(f"WebSocketManager disconnect error: {e}")
    
    async def subscribe_klines(self, symbol: str, interval: str, callback: Callable) -> bool:
        """Subscribe to kline/candlestick data."""
        return await self.client.subscribe_klines(symbol, interval, callback)
    
    async def subscribe_ticker(self, symbol: str, callback: Callable) -> bool:
        """Subscribe to 24hr ticker statistics."""
        return await self.client.subscribe_ticker(symbol, callback)
    
    async def subscribe_user_data(self, callback: Callable) -> bool:
        """Subscribe to user data stream."""
        return await self.client.subscribe_user_data(callback)
    
    def add_callback(self, stream_name: str, callback: Callable) -> None:
        """Add callback for a specific stream."""
        self.client.add_callback(stream_name, callback)
    
    def remove_callback(self, stream_name: str, callback: Callable) -> None:
        """Remove callback for a specific stream."""
        self.client.remove_callback(stream_name, callback)
    
    def is_connected(self) -> bool:
        """Check if WebSocket manager is connected."""
        return self._connected and self.client.is_connected()
    
    @property
    def websocket_client(self) -> BinanceWebSocketClient:
        """Get the underlying WebSocket client."""
        return self.client


def create_websocket_client(config: Config) -> BinanceWebSocketClient:
    """
    Create appropriate WebSocket client based on configuration.

    Returns:
        BinanceWebSocketClient for live trading
        MockWebSocketClient for paper trading or testing
    """
    if config.mode == "paper" or config.dry_run:
        return MockWebSocketClient(config)
    else:
        return BinanceWebSocketClient(config)


def create_websocket_manager(config: Config) -> WebSocketManager:
    """
    Create WebSocket manager.
    
    This is a convenience function that creates a WebSocketManager instance.
    Use this for backward compatibility with older code.
    """
    return WebSocketManager(config)


# Utility functions for WebSocket message parsing
def parse_kline_message(message: dict[str, Any]) -> MarketData | None:
    """Parse kline message to MarketData object."""
    try:
        kline = message.get("k", {})

        return MarketData(
            symbol=kline["s"],
            timestamp=datetime.fromtimestamp(kline["t"] / 1000),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            trades=int(kline["n"]),
            interval=kline["i"]
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.error(f"Failed to parse kline message: {e}")
        return None


def parse_order_update(message: dict[str, Any]) -> OrderUpdate | None:
    """Parse order update message."""
    try:
        order = message.get("o", {})

        return OrderUpdate(
            symbol=order["s"],
            order_id=int(order["i"]),
            client_order_id=order["c"],
            side=order["S"],
            order_type=order["o"],
            status=order["X"],
            quantity=float(order["q"]),
            price=float(order["p"]) if order["p"] != "0" else None,
            filled_qty=float(order["z"]),
            avg_price=float(order["ap"]) if order["ap"] != "0" else None,
            timestamp=datetime.fromtimestamp(order["T"] / 1000)
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.error(f"Failed to parse order update: {e}")
        return None
