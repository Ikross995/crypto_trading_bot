"""Utilities for loading bundled sample market data."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from core.types import MarketData

_DATA_DIR = Path(__file__).parent
_REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


class SampleSeries:
    """Lightweight container that behaves like a sequence and a scalar."""

    def __init__(self, values: Iterable[float]) -> None:
        self._values: List[float] = [float(v) for v in values]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, item):
        return self._values[item]

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return repr(self._values)

    def __float__(self) -> float:
        return float(self._values[-1])

    def _compare(self, other, op):
        return op(float(self), other)

    def __lt__(self, other):
        return self._compare(other, lambda a, b: a < b)

    def __le__(self, other):
        return self._compare(other, lambda a, b: a <= b)

    def __gt__(self, other):
        return self._compare(other, lambda a, b: a > b)

    def __ge__(self, other):
        return self._compare(other, lambda a, b: a >= b)

    def __bool__(self) -> bool:
        return bool(self._values)

    @property
    def last(self) -> float:
        return float(self)


def _resolve_file(symbol: str, timeframe: str) -> Path:
    filename = f"{symbol.upper()}_{timeframe}_sample.csv"
    return _DATA_DIR / filename


def _load_csv(filepath: Path) -> pd.DataFrame:
    if not filepath.exists():
        raise FileNotFoundError(f"Sample data not found: {filepath}")

    df = pd.read_csv(filepath)
    missing = [col for col in _REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Sample data missing required columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
    df.set_index("timestamp", inplace=True)
    return df


def load_sample_data(
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    start_rows: Optional[int] = None,
    end_rows: Optional[int] = None,
) -> pd.DataFrame:
    """Load candlestick sample data as a pandas DataFrame."""

    filepath = _resolve_file(symbol, timeframe)
    df = _load_csv(filepath)

    if start_rows is not None or end_rows is not None:
        df = df.iloc[start_rows:end_rows]

    return df


def get_latest_price(symbol: str = "BTCUSDT") -> float:
    """Return the latest closing price from the sample dataset."""

    df = load_sample_data(symbol)
    return float(df["close"].iloc[-1])


def get_sample_market_data(symbol: str = "BTCUSDT", rows: int = 30) -> MarketData:
    """Return recent market data formatted as :class:`MarketData`."""

    df = load_sample_data(symbol, end_rows=rows)
    if df.empty:
        raise ValueError(f"No sample data available for {symbol}")

    latest_close = float(df["close"].iloc[-1])
    bid = latest_close * 0.999
    ask = latest_close * 1.001
    volume = float(df["volume"].iloc[-1])

    market = MarketData(
        symbol=symbol.upper(),
        price=latest_close,
        bid=bid,
        ask=ask,
        volume=volume,
        timestamp=df.index[-1].to_pydatetime(),
    )

    # Attach rich OHLCV history for compatibility with older code
    market.open = SampleSeries(df["open"].tolist())  # type: ignore[attr-defined]
    market.high = SampleSeries(df["high"].tolist())  # type: ignore[attr-defined]
    market.low = SampleSeries(df["low"].tolist())  # type: ignore[attr-defined]
    market.close = SampleSeries(df["close"].tolist())  # type: ignore[attr-defined]
    market.volume = SampleSeries(df["volume"].tolist())  # type: ignore[attr-defined]

    return market


def get_available_symbols() -> list[str]:
    """List all symbols with bundled sample data."""

    symbols = []
    for file in _DATA_DIR.glob("*_1m_sample.csv"):
        symbols.append(file.stem.replace("_1m_sample", ""))
    return sorted(symbols)


def validate_sample_data() -> dict[str, bool]:
    """Validate integrity of bundled sample datasets."""

    results: dict[str, bool] = {}
    for symbol in get_available_symbols():
        try:
            df = load_sample_data(symbol)
            checks = [
                len(df) > 0,
                all(col in df.columns for col in _REQUIRED_COLUMNS),
                not df.isnull().any().any(),
                (df["high"] >= df["low"]).all(),
                (df["volume"] > 0).all(),
            ]
            results[symbol] = all(checks)
        except Exception:
            results[symbol] = False
    return results


__all__ = [
    "load_sample_data",
    "get_latest_price",
    "get_sample_market_data",
    "get_available_symbols",
    "validate_sample_data",
]
