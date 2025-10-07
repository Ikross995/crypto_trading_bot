"""
Type definitions for AI Trading Bot.

Defines all custom types, data classes and protocols used throughout the system.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from .constants import OrderSide, OrderStatus, OrderType, Regime, SignalDirection


class SignalSource(str, Enum):
    """Source of trading signals."""

    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    ML_MODEL = "ml_model"
    NEWS = "news"
    MANUAL = "manual"


class SignalType(str, Enum):
    """Type of trading signal."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Position:
    """Represents a trading position."""

    symbol: str
    side: int  # 1 for long, -1 for short, 0 for flat
    size: float
    entry_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: datetime | None = None

    @property
    def is_long(self) -> bool:
        return self.side > 0

    @property
    def is_short(self) -> bool:
        return self.side < 0

    @property
    def is_flat(self) -> bool:
        return self.side == 0 or abs(self.size) < 1e-8

    @property
    def notional_value(self) -> float:
        return abs(self.size * self.entry_price)


@dataclass
class Order:
    """Represents a trading order."""

    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    order_id: str | None = None
    client_order_id: str | None = None
    status: OrderStatus | None = None
    filled_qty: float = 0.0
    avg_price: float | None = None
    timestamp: datetime | None = None
    reduce_only: bool = False
    close_position: bool = False

    @property
    def remaining_qty(self) -> float:
        return max(0.0, self.quantity - self.filled_qty)

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)


@dataclass
class Trade:
    """Represents a completed trade."""

    symbol: str
    side: int  # 1 for long, -1 for short
    entry_price: float
    exit_price: float | None
    quantity: float
    pnl: float
    fee: float
    entry_time: datetime
    exit_time: datetime | None
    reason: str  # "TP1", "SL", "manual", etc.
    trade_id: str | None = None

    @property
    def duration(self) -> float | None:
        if self.exit_time and self.entry_time:
            return (self.exit_time - self.entry_time).total_seconds()
        return None

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def return_pct(self) -> float:
        if self.entry_price > 0:
            return (self.pnl / (self.entry_price * self.quantity)) * 100
        return 0.0


@dataclass
class Signal:
    """Represents a trading signal."""

    name: str
    direction: SignalDirection
    strength: float  # 0.0 to 1.0
    symbol: str
    price: float
    timestamp: datetime
    info: dict[str, Any]

    @property
    def is_bullish(self) -> bool:
        return self.direction == SignalDirection.BUY

    @property
    def is_bearish(self) -> bool:
        return self.direction == SignalDirection.SELL

    @property
    def is_neutral(self) -> bool:
        return self.direction == SignalDirection.WAIT


@dataclass
class MarketData:
    """Market data snapshot."""

    symbol: str
    price: float
    bid: float
    ask: float
    volume: float
    timestamp: datetime
    funding_rate: float | None = None
    open_interest: float | None = None


@dataclass
class Candle:
    """OHLCV candle data."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return self.high - self.low

    @property
    def is_green(self) -> bool:
        return self.close > self.open

    @property
    def is_red(self) -> bool:
        return self.close < self.open


@dataclass
class TechnicalIndicators:
    """Technical analysis indicators."""

    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    bb_upper: float | None = None
    bb_mid: float | None = None
    bb_lower: float | None = None
    bb_width: float | None = None
    atr: float | None = None
    adx: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    sma_slow: float | None = None
    vwap: float | None = None


@dataclass
class RegimeInfo:
    """Market regime information."""

    type: Regime
    adx: float
    bb_width: float
    confidence: float = 0.0


@dataclass
class RiskMetrics:
    """Risk management metrics."""

    position_size_usd: float
    leverage_used: float
    account_risk_pct: float
    daily_pnl: float
    max_drawdown: float
    var_95: float | None = None

    @property
    def is_risk_exceeded(self) -> bool:
        return self.account_risk_pct > 10.0  # 10% max account risk


@dataclass
class BacktestResult:
    """Backtest results and metrics."""

    symbol: str
    start_date: datetime
    end_date: datetime
    initial_balance: float
    final_balance: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    gross_profit: float
    gross_loss: float
    net_profit: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    expectancy: float

    @property
    def total_return(self) -> float:
        if self.initial_balance > 0:
            return (self.final_balance - self.initial_balance) / self.initial_balance
        return 0.0

    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return self.winning_trades / total if total > 0 else 0.0

    @property
    def avg_winner(self) -> float:
        return (
            self.gross_profit / self.winning_trades if self.winning_trades > 0 else 0.0
        )

    @property
    def avg_loser(self) -> float:
        return (
            abs(self.gross_loss) / self.losing_trades if self.losing_trades > 0 else 0.0
        )


# Protocol definitions for dependency injection
class PriceProvider(Protocol):
    """Protocol for price data providers."""

    def get_current_price(self, symbol: str) -> float:
        """Get current market price for symbol."""
        ...

    def get_historical_data(
        self, symbol: str, timeframe: str, limit: int
    ) -> list[Candle]:
        """Get historical candle data."""
        ...


class OrderExecutor(Protocol):
    """Protocol for order execution."""

    def place_order(self, order: Order) -> Order:
        """Place a new order."""
        ...

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an existing order."""
        ...

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open orders."""
        ...


@dataclass
class OrderUpdate:
    """WebSocket order update message."""

    symbol: str
    order_id: int
    client_order_id: str
    side: str
    order_type: str
    status: str
    quantity: float
    price: float | None
    filled_qty: float
    avg_price: float | None
    timestamp: datetime

    @property
    def remaining_qty(self) -> float:
        return max(0.0, self.quantity - self.filled_qty)

    @property
    def is_filled(self) -> bool:
        return self.status == "FILLED"


@dataclass
class PositionUpdate:
    """WebSocket position update message."""

    symbol: str
    position_side: str
    position_amount: float
    entry_price: float
    unrealized_pnl: float
    timestamp: datetime

    @property
    def is_long(self) -> bool:
        return float(self.position_amount) > 0

    @property
    def is_short(self) -> bool:
        return float(self.position_amount) < 0

    @property
    def is_flat(self) -> bool:
        return abs(float(self.position_amount)) < 1e-8


class PositionManager(Protocol):
    """Protocol for position management."""

    def get_position(self, symbol: str) -> Position:
        """Get current position for symbol."""
        ...

    def get_all_positions(self) -> list[Position]:
        """Get all open positions."""
        ...


# Type aliases for commonly used types
PriceDict = dict[str, float]
IndicatorDict = dict[str, float | int | str]
SignalDict = dict[str, Any]
ConfigDict = dict[str, Any]
SymbolFilters = dict[str, dict[str, float]]

# Union types
Numeric = int | float | Decimal
TimestampType = int | float | datetime
OrderID = str | int
