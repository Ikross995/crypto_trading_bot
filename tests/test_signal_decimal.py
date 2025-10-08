from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timedelta

from core.config import Config
from strategy.signals import SignalGenerator, SignalType


def test_signal_generator_handles_decimal_market_data():
    """Ensure Decimal based price feeds do not break signal math."""

    config = Config()
    generator = SignalGenerator(config)

    base_time = datetime.now() - timedelta(minutes=10)
    prices = [Decimal("10000") + Decimal(i) for i in range(1, 16)]
    timestamps = [base_time + timedelta(minutes=i) for i in range(len(prices))]

    market_data = {
        "symbol": "BTCUSDT",
        "close": prices,
        "timestamp": timestamps,
    }

    signal = generator.generate_signal(market_data)

    assert signal is not None, "Expected a signal when fast MA diverges from slow MA"
    assert signal.signal_type == SignalType.BUY
    assert isinstance(signal.metadata["fast_ma"], float)
    assert isinstance(signal.metadata["slow_ma"], float)
    assert isinstance(signal.metadata["ma_diff_pct"], float)
