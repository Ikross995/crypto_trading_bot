"""Lightweight market data simulator used for offline tests and demos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from typing import Dict, List, Optional

from core.config import Config

getcontext().prec = 18


@dataclass
class SimulatedMarketData:
    """Container that mimics the structure of real market data."""

    symbol: str
    interval: str
    timestamp: List[datetime]
    open: List[Decimal]
    high: List[Decimal]
    low: List[Decimal]
    close: List[Decimal]
    volume: List[Decimal]


class MarketSimulator:
    """Generate deterministic synthetic market data for tests."""

    _BASE_PRICES: Dict[str, Decimal] = {
        "BTCUSDT": Decimal("97000"),
        "ETHUSDT": Decimal("3500"),
        "SOLUSDT": Decimal("180"),
        "ADAUSDT": Decimal("0.45"),
    }

    def __init__(self, config: Optional[Config] = None, seed: Optional[int] = None) -> None:
        self.config = config or Config()
        self._seed = seed or 42
        self._state: Dict[str, Dict[str, Decimal | datetime]] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Initialise simulator state."""
        self._initialized = True

    def _ensure_state(self, symbol: str) -> Dict[str, Decimal | datetime]:
        symbol = symbol.upper()
        if symbol not in self._state:
            start_price = self._BASE_PRICES.get(symbol, Decimal("100"))
            self._state[symbol] = {
                "price": start_price,
                "time": datetime.now(tz=timezone.utc),
            }
        return self._state[symbol]

    @staticmethod
    def _interval_to_delta(interval: str) -> timedelta:
        if interval.endswith("m"):
            return timedelta(minutes=int(interval[:-1] or 1))
        if interval.endswith("h"):
            return timedelta(hours=int(interval[:-1] or 1))
        if interval.endswith("d"):
            return timedelta(days=int(interval[:-1] or 1))
        return timedelta(minutes=1)

    def _random_step(self, symbol: str) -> Decimal:
        state = self._ensure_state(symbol)
        price = Decimal(state["price"])  # type: ignore[index]
        # Simple pseudo-random walk based on deterministic seed and timestamp
        timestamp: datetime = state["time"]  # type: ignore[index]
        key = hash((symbol, int(timestamp.timestamp()), self._seed))
        change = (key % 2000 - 1000) / Decimal("100000")  # +/- 1%
        new_price = price * (Decimal("1") + change)
        if new_price <= 0:
            new_price = price
        state["price"] = new_price
        state["time"] = timestamp + timedelta(seconds=1)
        return Decimal(new_price)

    def get_current_price(self, symbol: str) -> Decimal:
        self.initialize()
        price = self._random_step(symbol)
        return price.quantize(Decimal("0.01"))

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 500) -> SimulatedMarketData:
        self.initialize()
        symbol = symbol.upper()
        state = self._ensure_state(symbol)
        step = self._interval_to_delta(interval)
        base_time: datetime = state["time"]  # type: ignore[index]

        timestamps: List[datetime] = []
        opens: List[Decimal] = []
        highs: List[Decimal] = []
        lows: List[Decimal] = []
        closes: List[Decimal] = []
        volumes: List[Decimal] = []

        price = Decimal(state["price"])  # type: ignore[index]
        for _ in range(int(limit)):
            open_price = price
            high_price = open_price * Decimal("1.003")
            low_price = open_price * Decimal("0.997")
            close_price = self._random_step(symbol)
            volume = Decimal("10") * (close_price / Decimal("100"))

            timestamps.append(base_time)
            opens.append(open_price.quantize(Decimal("0.01")))
            highs.append(high_price.quantize(Decimal("0.01")))
            lows.append(low_price.quantize(Decimal("0.01")))
            closes.append(close_price.quantize(Decimal("0.01")))
            volumes.append(volume.quantize(Decimal("0.0001")))

            base_time += step
            price = close_price

        state["price"] = price
        state["time"] = base_time

        return SimulatedMarketData(
            symbol=symbol,
            interval=interval,
            timestamp=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            volume=volumes,
        )
