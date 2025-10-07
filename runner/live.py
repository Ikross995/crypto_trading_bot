# work/runner/live.py
"""
Live trading engine (compat-safe).

This file provides a robust, defensive implementation of LiveTradingEngine and run_live_trading()
that tolerates different shapes of signals and missing market-data backends. It preserves the
public API expected by cli_integrated.py and runner.__init__.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union, Callable

try:
    # Optional structured logging init (present in the user's project)
    from infra.logging import setup_structured_logging  # type: ignore
except Exception:  # pragma: no cover
    def setup_structured_logging() -> None:
        pass

try:
    from core.config import Config  # type: ignore
except Exception:  # pragma: no cover
    @dataclass
    class Config:
        mode: str = "live"
        dry_run: bool = True
        testnet: bool = True
        symbols: List[str] = None
        symbol: str = "BTCUSDT"
        timeframe: str = "1m"
        leverage: int = 5
        risk_per_trade_pct: float = 0.5
        max_daily_loss_pct: float = 5.0
        min_notional_usdt: float = 5.0
        maker_fee: float = 0.0002
        taker_fee: float = 0.0004

# Market data
try:
    from exchange.market_data import MarketDataProvider  # type: ignore
except Exception:  # pragma: no cover
    MarketDataProvider = None  # type: ignore

# Optional modules; we only use them when available.
try:
    from strategy.exits import ExitManager  # type: ignore
except Exception:  # pragma: no cover
    ExitManager = None  # type: ignore

try:
    from infra.metrics import MetricsCollector  # type: ignore
except Exception:  # pragma: no cover
    MetricsCollector = None  # type: ignore

logger = logging.getLogger(__name__)


# --- Internal helper structures -------------------------------------------------------

@dataclass
class NormalizedSignal:
    symbol: str
    side: str              # "BUY" or "SELL"
    strength: float = 0.0  # 0..1
    entry_price: Optional[float] = None
    timestamp: datetime = datetime.now(timezone.utc)
    meta: Dict[str, Any] = None

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            xs = x.strip()
            if xs == "":
                return None
            return float(xs)
    except Exception:
        return None
    return None

def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Try attributes and dict-keys in order."""
    for n in names:
        # attribute
        if hasattr(obj, n):
            try:
                return getattr(obj, n)
            except Exception:
                pass
        # dict-like
        try:
            return obj[n]  # type: ignore
        except Exception:
            pass
    return default

def _enum_value(x: Any) -> Any:
    if x is None:
        return None
    try:
        return x.value  # enum or pydantic types
    except Exception:
        return x

def normalize_signal_obj(raw: Any, symbol_default: Optional[str] = None) -> Optional[NormalizedSignal]:
    """
    Accept signal in many shapes (dataclass, pydantic model, dict, plain strings).
    Returns a NormalizedSignal or None if cannot be understood.
    """
    if raw is None:
        return None

    # If signal is a plain string like "BUY"/"SELL", treat as no-trade fallback (skip).
    if isinstance(raw, str):
        s = raw.strip().upper()
        if s in {"BUY", "SELL"}:
            # No price/strength -> skip trading because we can't size risk sanely.
            logger.warning("Signal string (%s) has no price/strength — skipping.", s)
            return None
        logger.debug("Ignoring unknown string signal: %r", raw)
        return None

    # Convenience: Some generators return (side, strength) tuple
    if isinstance(raw, (tuple, list)) and len(raw) in (2, 3):
        side = str(raw[0]).upper()
        strength = float(raw[1]) if raw[1] is not None else 0.0
        price = _to_float(raw[2]) if len(raw) == 3 else None
        if side in {"BUY", "SELL"}:
            return NormalizedSignal(
                symbol=symbol_default or "UNKNOWN",
                side=side,
                strength=strength,
                entry_price=price,
                timestamp=datetime.now(timezone.utc),
                meta={"shape": "tuple"},
            )

    # General case: object/dict with fields
    side_raw = _get(raw, "side", "signal_type", "direction", default=None)
    side_raw = _enum_value(side_raw)
    side_str = str(side_raw).upper() if side_raw is not None else None
    if side_str and side_str not in {"BUY", "SELL"}:
        # Could be "SignalType.BUY"
        if "." in side_str:
            side_str = side_str.split(".")[-1]

    symbol = _get(raw, "symbol", default=symbol_default or "UNKNOWN")
    strength = _get(raw, "strength", "confidence", "score", default=0.0) or 0.0
    entry_price = _to_float(_get(raw, "entry_price", "price", "entry", default=None))
    ts = _get(raw, "timestamp", default=None) or datetime.now(timezone.utc)
    meta: Dict[str, Any] = {}

    # Sometimes generators add 'metadata' or 'meta'
    md = _get(raw, "metadata", "meta", default=None)
    if isinstance(md, dict):
        meta.update(md)

    # If we still don't have a valid side, skip.
    if side_str not in {"BUY", "SELL"}:
        logger.debug("Cannot normalize signal side from %r — skipping.", raw)
        return None

    # Coerce strength
    try:
        strength = float(strength)
    except Exception:
        strength = 0.0

    return NormalizedSignal(
        symbol=str(symbol),
        side=side_str,
        strength=strength,
        entry_price=entry_price,
        timestamp=ts if isinstance(ts, datetime) else datetime.now(timezone.utc),
        meta=meta,
    )


# --- Live engine ----------------------------------------------------------------------

class LiveTradingEngine:
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("runner.live")
        self.running = False
        self.iteration = 0

        # Symbols
        symbols = getattr(config, "symbols", None)
        if not symbols:
            sym = getattr(config, "symbol", None)
            symbols = [sym] if sym else ["BTCUSDT"]
        self.symbols: List[str] = [str(s).upper() for s in symbols]

        # Market data provider
        self.market: Optional[MarketDataProvider] = None
        try:
            if MarketDataProvider is not None:
                self.market = MarketDataProvider()
        except Exception as e:  # pragma: no cover
            self.logger.warning("MarketDataProvider init failed: %s", e)

        # Signal generator
        self.signaler = self._init_signaler()

        # Exits / metrics (optional)
        self.exit_mgr = None
        if ExitManager:
            try:
                self.exit_mgr = ExitManager(config)  # type: ignore
            except Exception as e:
                self.logger.debug("ExitManager init failed: %s", e)

        self.metrics = None
        if MetricsCollector:
            try:
                self.metrics = MetricsCollector()  # type: ignore
            except Exception as e:
                self.logger.debug("MetricsCollector init failed: %s", e)

        # Accounting
        self.equity_usdt = float(getattr(config, "paper_equity", 1000.0))
        self.min_notional = float(getattr(config, "min_notional_usdt", 5.0))
        self.leverage = int(getattr(config, "leverage", 5))
        self.risk_pct = float(getattr(config, "risk_per_trade_pct", 0.5))
        self.timeframe = str(getattr(config, "timeframe", "1m"))
        self.dry_run = bool(getattr(config, "dry_run", True))

        self.logger.info("Live trading engine initialized")

    def _init_signaler(self) -> Any:
        # Best-effort import; we tolerate absence
        try:
            from strategy.signals import SignalGenerator  # type: ignore
            try:
                sg = SignalGenerator(self.config)  # type: ignore
            except Exception:
                sg = SignalGenerator()  # type: ignore
            # Optional init
            for name in ("initialize", "init", "setup"):
                fn = getattr(sg, name, None)
                if callable(fn):
                    try:
                        r = fn()
                        if asyncio.iscoroutine(r):
                            # Don't block here
                            asyncio.create_task(r)  # fire and forget
                    except Exception as e:
                        self.logger.debug("SignalGenerator.%s failed: %s", name, e)
            return sg
        except Exception as e:
            self.logger.warning("SignalGenerator not available: %s", e)
            return object()

    async def _produce_raw_signal(self, symbol: str, market_data: Any) -> Any:
        """Try various method names / signatures to call user's signal generator."""
        sg = self.signaler
        # Try method variants
        cand: List[Tuple[str, Tuple[Any, ...]]] = [
            ("get_signal", (symbol, market_data, self.config)),
            ("get_signal", (symbol, market_data)),
            ("get_signal", (market_data,)),
            ("generate", (symbol, market_data, self.config)),
            ("generate", (symbol, market_data)),
            ("generate", (market_data,)),
            ("generate_signal", (symbol, market_data, self.config)),
            ("generate_signal", (symbol, market_data)),
            ("generate_signal", (market_data,)),
            ("compute", (symbol, market_data)),
            ("signal", (symbol, market_data)),
        ]
        for name, args in cand:
            fn = getattr(sg, name, None)
            if not callable(fn):
                continue
            try:
                res = fn(*args)
                if asyncio.iscoroutine(res):
                    res = await res
                return res
            except TypeError:
                # Signature mismatch, try next
                continue
            except Exception as e:
                self.logger.debug("SignalGenerator.%s error: %s", name, e)
                break  # avoid spamming
        return None

    async def _latest_price(self, symbol: str) -> Optional[float]:
        if not self.market:
            return None
        # Try explicit ticker first
        try:
            if hasattr(self.market, "get_ticker") and callable(getattr(self.market, "get_ticker")):
                t = await self.market.get_ticker(symbol)
                price = _to_float(_get(t, "price", default=None))
                if price:
                    return price
        except Exception as e:
            self.logger.debug("get_ticker failed: %s", e)
        # Try small kline fetch
        try:
            if hasattr(self.market, "get_candles"):
                kl = await self.market.get_candles(symbol, self.timeframe, limit=2)  # type: ignore
                if isinstance(kl, list) and kl:
                    last = kl[-1]
                    price = _to_float(_get(last, "close", "c", "price", default=None))
                    return price
        except Exception as e:
            self.logger.debug("get_candles failed: %s", e)
        return None

    def _position_size_qty(self, price: Optional[float]) -> Optional[float]:
        """
        Conservative sizing by notional budget: quantity = (equity * risk% * leverage) / price
        Never divide by zero. Enforce min_notional.
        """
        p = _to_float(price)
        if not p or p <= 0:
            return None
        equity = float(self.equity_usdt)
        budget = max(0.0, equity * (self.risk_pct / 100.0))  # convert percent to fraction
        notional = max(self.min_notional, budget) * max(1, self.leverage)
        qty = notional / p
        if qty <= 0:
            return None
        return qty

    async def start(self) -> None:
        if callable(setup_structured_logging):
            try:
                setup_structured_logging()
            except Exception:
                pass
        self.running = True
        self.logger.info("Starting live trading engine...")
        if self.metrics:
            try:
                self.metrics.start()  # type: ignore
            except Exception:
                pass
        await self._run_trading_loop()

    async def stop(self) -> None:
        self.running = False
        if self.metrics:
            try:
                self.metrics.stop()  # type: ignore
            except Exception:
                pass
        self.logger.info("Live trading engine stopped")

    async def _run_trading_loop(self) -> None:
        self.logger.info("Starting main trading loop")
        # Default: iterate forever; we will sleep 1s between cycles to be gentle.
        while self.running:
            self.iteration += 1
            try:
                for symbol in self.symbols:
                    await self._process_symbol(symbol)
            except Exception as e:
                self.logger.error("Error in trading loop: %s", e)
            # Throttle loop
            await asyncio.sleep(1.0)

    async def _process_symbol(self, symbol: str) -> None:
        # Fetch market data for the signaler; if fails, pass None (signaler will fallback)
        md: Any = None
        if self.market and hasattr(self.market, "get_candles"):
            try:
                md = await self.market.get_candles(symbol, self.timeframe, limit=50)  # type: ignore
            except Exception as e:
                self.logger.debug("get_candles(%s) error: %s", symbol, e)

        raw = await self._produce_raw_signal(symbol, md)
        sig = normalize_signal_obj(raw, symbol_default=symbol)
        if not sig:
            return  # nothing actionable

        # Ensure we have a price to size the order
        price = sig.entry_price or await self._latest_price(symbol)
        qty = self._position_size_qty(price)
        if not price or not qty:
            self.logger.debug("Skip %s: missing price/qty (price=%s qty=%s)", symbol, price, qty)
            return

        # Dry run: we just log the intended action
        self.logger.info("📊 Signal: %s %s @ %.2f (strength=%.2f) -> qty=%.6f [DRY-RUN=%s]",
                         sig.side, symbol, price, sig.strength, qty, self.dry_run)

        # In real mode we'd place orders here; in dry-run/paper, skip.
        # We still call exit manager hooks if available (they will no-op in dry-run).
        if self.exit_mgr and hasattr(self.exit_mgr, "on_new_signal"):
            try:
                r = self.exit_mgr.on_new_signal(symbol, sig.side, price, qty)  # type: ignore
                if asyncio.iscoroutine(r):
                    await r
            except Exception as e:
                self.logger.debug("ExitManager.on_new_signal error: %s", e)


# --- Entry point ----------------------------------------------------------------------

async def run_live_trading(config: Config) -> None:
    engine = LiveTradingEngine(config)
    try:
        await engine.start()
    finally:
        await engine.stop()
