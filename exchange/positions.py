"""Lightweight position manager used by demos and tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from core.config import Config, get_config
from core.constants import PositionSide
from .client import BinanceClient, MockBinanceClient

logger = logging.getLogger(__name__)


class _AwaitableResult:
    """Container that works in both sync and async contexts."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        yield
        return self._value

    def __getattr__(self, item):
        return getattr(self._value, item)

    def __iter__(self):  # pragma: no cover - rarely used
        if hasattr(self._value, "__iter__"):
            return iter(self._value)
        return iter([self._value])

    def __bool__(self) -> bool:
        return bool(self._value)

    def unwrap(self):
        return self._value


@dataclass
class ManagedPosition:
    symbol: str
    side: PositionSide
    size: Decimal
    entry_price: Decimal
    current_price: Decimal
    realized_pnl: Decimal = Decimal("0")
    opened_at: datetime = datetime.utcnow()

    @property
    def notional(self) -> Decimal:
        return self.size * self.current_price

    @property
    def direction(self) -> Decimal:
        return Decimal("1") if self.side == PositionSide.LONG else Decimal("-1")

    @property
    def unrealized_pnl(self) -> Decimal:
        return (self.current_price - self.entry_price) * self.size * self.direction

    def update_price(self, price: Decimal) -> None:
        self.current_price = price


class PositionManager:
    """Stateful manager for paper-trading style position tracking."""

    def __init__(self, source: Optional[object] = None):
        if isinstance(source, BinanceClient):
            self.client = source
            self.config = get_config()
        else:
            self.config = source if isinstance(source, Config) else get_config()
            starting_balance = getattr(self.config, "starting_balance", 10000.0)
            self.client = MockBinanceClient(starting_balance=starting_balance)
        self._positions: Dict[str, ManagedPosition] = {}
        self._last_prices: Dict[str, Decimal] = {}
        self._pnl_history: List[Decimal] = []
        logger.debug("PositionManager initialized with symbols: %s", self.config.symbols)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Prepare internal caches."""
        self._positions.clear()
        self._last_prices.clear()
        self._pnl_history.clear()

    # ------------------------------------------------------------------
    # Position operations
    # ------------------------------------------------------------------
    def has_position(self, symbol: str) -> bool:
        pos = self._positions.get(symbol.upper())
        return bool(pos and pos.size > 0)

    def update_market_price(self, symbol: str, price: Decimal | float) -> None:
        dec_price = Decimal(str(price))
        self._last_prices[symbol.upper()] = dec_price
        if symbol.upper() in self._positions:
            self._positions[symbol.upper()].update_price(dec_price)

    def update_position(
        self,
        *,
        symbol: str,
        side: PositionSide,
        size: Decimal | float,
        price: Decimal | float,
    ) -> _AwaitableResult:
        sym = symbol.upper()
        quantity = Decimal(str(size)).copy_abs()
        entry = Decimal(str(price))
        current = self._last_prices.get(sym, entry)
        position = ManagedPosition(
            symbol=sym,
            side=side,
            size=quantity,
            entry_price=entry,
            current_price=current,
        )
        self._positions[sym] = position
        self._last_prices[sym] = current
        logger.debug("Position updated: %s", position)
        return _AwaitableResult(position)

    def get_position(self, symbol: str, *, default=None) -> Optional[ManagedPosition]:
        return self._positions.get(symbol.upper(), default)

    def get_all_positions(self) -> List[ManagedPosition]:
        return list(self._positions.values())

    def get_positions(self) -> _AwaitableResult:
        return _AwaitableResult(self.get_all_positions())

    def close_position(self, symbol: str, price: Decimal | float) -> _AwaitableResult:
        sym = symbol.upper()
        if sym not in self._positions:
            return _AwaitableResult(Decimal("0"))
        position = self._positions.pop(sym)
        close_price = Decimal(str(price))
        pnl = (close_price - position.entry_price) * position.size * position.direction
        position.realized_pnl += pnl
        self._pnl_history.append(pnl)
        if isinstance(self.client, MockBinanceClient):
            self.client._paper_balance += pnl  # type: ignore[attr-defined]
        logger.debug("Closed position %s with pnl %s", sym, pnl)
        return _AwaitableResult(pnl)

    # ------------------------------------------------------------------
    # Account helpers
    # ------------------------------------------------------------------
    def get_account_balance(self) -> float:
        try:
            return float(self.client.get_account_balance())
        except Exception:  # pragma: no cover - defensive
            return float(self.client.get_balance())

    def get_balance(self) -> Decimal:
        bal = self.client.get_balance()
        return bal if isinstance(bal, Decimal) else Decimal(str(bal))

    def calculate_position_size(self, symbol: str, price: Decimal | float) -> Decimal:
        market_price = Decimal(str(price))
        balance = self.get_balance()
        risk_pct = Decimal(str(self.config.risk_per_trade))
        if market_price <= 0:
            return Decimal("0")
        size = (balance * risk_pct) / market_price
        logger.debug("Calculated position size for %s: %s", symbol, size)
        return size

    def get_position_risk_metrics(self, symbol: str) -> Dict[str, float]:
        position = self.get_position(symbol)
        balance = float(self.get_balance())
        if not position or balance <= 0:
            return {
                "position_size_usd": 0.0,
                "account_risk_pct": 0.0,
                "leverage_used": 0.0,
                "unrealized_pnl_pct": 0.0,
            }
        notional = float(position.notional)
        risk_pct = float((position.size * position.entry_price) / balance) if balance else 0.0
        leverage = notional / balance if balance else 0.0
        unrealized_pct = float(position.unrealized_pnl / balance) * 100.0 if balance else 0.0
        return {
            "position_size_usd": notional,
            "account_risk_pct": risk_pct * 100.0,
            "leverage_used": leverage,
            "unrealized_pnl_pct": unrealized_pct,
        }

    def setup_symbol(self, symbol: str) -> bool:
        logger.debug("Setup symbol called for %s", symbol)
        return True

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        if symbol:
            self._positions.pop(symbol.upper(), None)
            self._last_prices.pop(symbol.upper(), None)
        else:
            self._positions.clear()
            self._last_prices.clear()

    # Compatibility async-style adapters --------------------------------
    def sync_positions(self) -> _AwaitableResult:
        return self.get_positions()

    async def initialize_async(self) -> None:  # pragma: no cover - optional
        self.initialize()

    async def get_positions_async(self) -> List[ManagedPosition]:  # pragma: no cover
        return self.get_positions().unwrap()

    async def update_position_async(self, *args, **kwargs):  # pragma: no cover
        return self.update_position(*args, **kwargs).unwrap()

    async def close_position_async(self, symbol: str, price: Decimal | float):  # pragma: no cover
        return self.close_position(symbol, price).unwrap()


__all__ = ["PositionManager", "ManagedPosition"]
