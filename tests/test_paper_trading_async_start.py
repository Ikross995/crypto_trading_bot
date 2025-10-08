import asyncio
from decimal import Decimal
import importlib
import sys
import types

from core.config import Config


class DummyMarketDataClient:
    last_instance: "DummyMarketDataClient | None" = None

    def __init__(self, config):
        self.config = config
        self.initialized = False
        DummyMarketDataClient.last_instance = self

    def initialize(self):
        self.initialized = True

    def get_current_price(self, symbol: str) -> Decimal:
        return Decimal("30000")

    def get_klines(self, *, symbol: str, interval: str, limit: int):
        return []


class DummyPositionManager:
    last_instance: "DummyPositionManager | None" = None

    def __init__(self, config):
        self.config = config
        self.initialized = False
        DummyPositionManager.last_instance = self

    async def initialize(self):
        await asyncio.sleep(0)
        self.initialized = True


class DummySignalGenerator:
    last_instance: "DummySignalGenerator | None" = None

    def __init__(self, config):
        self.config = config
        self.initialized = False
        DummySignalGenerator.last_instance = self

    async def initialize(self):
        await asyncio.sleep(0)
        self.initialized = True

    def generate_signal(self, market_data):
        return None


def test_paper_engine_start_awaits_async_initializers(monkeypatch):
    compat_stub = types.SimpleNamespace(apply=lambda: None)
    monkeypatch.setitem(sys.modules, "compat_complete", compat_stub)
    monkeypatch.setitem(sys.modules, "compat", compat_stub)
    monkeypatch.delitem(sys.modules, "runner", raising=False)
    monkeypatch.delitem(sys.modules, "runner.paper", raising=False)
    paper_module = importlib.import_module("runner.paper")

    monkeypatch.setattr(paper_module, "BinanceMarketDataClient", DummyMarketDataClient)
    monkeypatch.setattr(paper_module, "PositionManager", DummyPositionManager)
    monkeypatch.setattr(paper_module, "SignalGenerator", DummySignalGenerator)

    run_called = False

    def _fail_run(*args, **kwargs):
        nonlocal run_called
        run_called = True
        raise AssertionError("asyncio.run should not be invoked inside paper engine startup")

    monkeypatch.setattr(paper_module.asyncio, "run", _fail_run)

    config = Config(symbols=["BTCUSDT"])
    engine = paper_module.PaperTradingEngine(config)

    async def _start_and_stop():
        await engine.start()
        engine.stop()

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_start_and_stop())
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    assert DummyMarketDataClient.last_instance is not None
    assert DummyMarketDataClient.last_instance.initialized
    assert DummyPositionManager.last_instance is not None
    assert DummyPositionManager.last_instance.initialized
    assert DummySignalGenerator.last_instance is not None
    assert DummySignalGenerator.last_instance.initialized
    assert not run_called