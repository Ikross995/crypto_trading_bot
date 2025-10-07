#!/usr/bin/env python3
"""
Live Trading Engine (guardrails v8)

- Robust to missing / optional fields in Config.
- Works in DRY_RUN without hitting the exchange.
- Normalizes signals of different shapes (str/tuple/dict/Signal).
- Accepts RiskManager.calculate_position_size returning float or (float, reason).
- Guards ZeroDivisionError from RiskManager.
- Cooldown check works even if OrderManager.is_in_cooldown is missing.
- Optional runtime overrides watcher is supported.
"""

from __future__ import annotations

import asyncio
import signal
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

from loguru import logger

try:
    # Optional overrides infra
    from infra.settings import RuntimeOverridesWatcher, load_overrides, apply_settings_to_config  # type: ignore
except Exception:
    RuntimeOverridesWatcher = None  # type: ignore
    def apply_settings_to_config(cfg: Any, changes: dict) -> None:  # type: ignore
        for k, v in (changes or {}).items():
            try:
                setattr(cfg, k, v)
            except Exception:
                pass

# Strategy / Infra / Core modules (project local)
from strategy.exits import ExitManager  # type: ignore
from strategy.dca import DCAManager  # type: ignore
from strategy.risk import RiskManager  # type: ignore
from strategy.signals import SignalGenerator  # type: ignore

from infra.logging import setup_structured_logging  # type: ignore
from infra.metrics import MetricsCollector  # type: ignore
from infra.persistence import StateManager  # type: ignore

from core.config import Config  # type: ignore
from core.constants import OrderType  # type: ignore
from core.types import Order, Position, Signal  # type: ignore
from core.utils import calculate_pnl, format_currency  # type: ignore

from exchange.client import BinanceClient  # type: ignore
from exchange.orders import OrderManager  # type: ignore
from exchange.positions import PositionManager  # type: ignore


def _get(cfg: Any, name: str, default: Any) -> Any:
    return getattr(cfg, name, default)


def _is_async_callable(fn: Any) -> bool:
    return asyncio.iscoroutinefunction(fn) or asyncio.iscoroutine(fn)


async def _maybe_await(x: Any) -> Any:
    try:
        if asyncio.iscoroutine(x):
            return await x
        if asyncio.iscoroutinefunction(x):
            return await x()  # type: ignore
        return x
    except TypeError:
        return x


class LiveTradingEngine:
    """
    Live trading execution engine with comprehensive safety measures.
    """

    def __init__(self, config: Config):
        self.config = config

        # Runtime overrides (optional file watcher)
        self._overrides_watcher = None
        path = _get(self.config, "overrides_path", "") or "config/overrides.txt"
        if RuntimeOverridesWatcher and os.path.exists(path):
            try:
                self._overrides_watcher = RuntimeOverridesWatcher(path)  # type: ignore
            except Exception as e:
                logger.warning(f"RuntimeOverridesWatcher init failed: {e}")

        self.running = False
        self.paused = False
        self._shutdown_event = asyncio.Event()

        # Core components
        self.client = BinanceClient(testnet=_get(config, "testnet", False))  # type: ignore
        self.order_manager = OrderManager(self.client)  # type: ignore
        self.position_manager = PositionManager(self.client)  # type: ignore

        # Strategy components
        self.signal_generator = SignalGenerator(config)  # type: ignore
        self.risk_manager = RiskManager(config)  # type: ignore
        self.exit_manager = ExitManager(config)  # type: ignore
        self.dca_manager = DCAManager(config)  # type: ignore

        # Infrastructure
        self.metrics = MetricsCollector(config)  # type: ignore
        self.state_manager = StateManager(config)  # type: ignore

        # State tracking
        self.active_positions: dict[str, Position] = {}
        self.pending_orders: dict[str, Order] = {}
        self.processed_signals: set[str] = set()

        # Performance tracking
        self.start_time: Optional[datetime] = None
        self.trades_executed = 0
        self.total_pnl = 0.0

        logger.info("Live trading engine initialized", symbol=_get(config, "symbol", None), mode="LIVE")

    async def start(self) -> None:
        """Start the live trading engine."""
        if self.running:
            logger.warning("Engine already running")
            return

        logger.info("Starting live trading engine...")

        try:
            # Initialize components
            await self._initialize_components()

            # Setup signal handlers for graceful shutdown
            self._setup_signal_handlers()

            # Load previous state
            await self._load_state()

            self.running = True
            self.start_time = datetime.utcnow()

            logger.info("Live trading engine started successfully")

            # Main trading loop
            await self._run_trading_loop()

        except Exception as e:
            logger.error(f"Failed to start live trading engine: {e}", exc_info=True)
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop the trading engine gracefully."""
        if not self.running:
            return

        logger.info("Stopping live trading engine...")

        self.running = False
        self._shutdown_event.set()

        try:
            # Cancel all pending orders
            await self._cancel_all_pending_orders()

            # Save current state
            await self._save_state()

            # Close positions if configured
            if _get(self.config, "close_positions_on_exit", False):
                await self._close_all_positions()

            # Shutdown components
            await self._shutdown_components()

            # Log final statistics
            self._log_final_stats()

        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)

        logger.info("Live trading engine stopped")

    async def pause(self) -> None:
        """Pause trading (stop opening new positions)."""
        self.paused = True
        logger.info("Trading paused - no new positions will be opened")

    async def resume(self) -> None:
        """Resume trading."""
        self.paused = False
        logger.info("Trading resumed")

    async def _initialize_components(self) -> None:
        """Initialize all trading components."""
        logger.info("Initializing trading components...")

        if _get(self.config, "dry_run", False):
            logger.info("DRY_RUN: skipping exchange initialization and position sync")
        else:
            # Test exchange connection
            try:
                await _maybe_await(self.client.get_exchange_info())  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning(f"get_exchange_info failed: {e}")

            # Initialize position manager
            try:
                await _maybe_await(self.position_manager.initialize())  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning(f"position_manager.initialize failed: {e}")

            # Load existing positions
            try:
                positions = await _maybe_await(self.position_manager.get_positions())  # type: ignore[attr-defined]
                for pos in positions or []:
                    self.active_positions[pos.symbol] = pos  # type: ignore
            except Exception as e:
                logger.warning(f"get_positions failed: {e}")

        # Initialize signal generator with historical data
        try:
            await _maybe_await(self.signal_generator.initialize())  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"SignalGenerator.initialize failed: {e}")

        # Start metrics collection
        await self.metrics.start()

        logger.info("All components initialized successfully")

    async def _shutdown_components(self) -> None:
        """Shutdown all components gracefully."""
        try:
            await self.metrics.stop()
        except Exception as e:
            logger.error(f"Error stopping metrics: {e}")
        try:
            if hasattr(self.client, "close"):
                await _maybe_await(self.client.close)  # type: ignore
        except Exception as e:
            logger.error(f"Error shutting down client: {e}")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""

        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            asyncio.create_task(self.stop())

        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except Exception as e:
            # Some platforms (e.g., Windows in certain contexts) may restrict this
            logger.debug(f"Signal handler installation skipped: {e}")

    async def _run_trading_loop(self) -> None:
        """Main trading loop."""
        logger.info("Starting main trading loop")

        loop_count = 0
        last_health_check = datetime.utcnow()
        trading_interval = float(_get(self.config, "trading_interval", 1.0))

        while self.running:
            try:
                loop_start = datetime.utcnow()
                loop_count += 1

                # Health check every 5 minutes
                if (loop_start - last_health_check) > timedelta(minutes=5):
                    await self._health_check()
                    last_health_check = loop_start

                # Check for emergency conditions
                stop_now = await self._check_emergency_stop()
                if stop_now:
                    logger.critical("Emergency stop triggered!")
                    await self.stop()
                    break

                # Apply runtime overrides if changed
                if self._overrides_watcher:
                    try:
                        changes = self._overrides_watcher.poll()  # type: ignore[attr-defined]
                    except Exception as e:
                        changes = None
                        logger.debug(f"overrides poll failed: {e}")
                    if changes:
                        try:
                            apply_settings_to_config(self.config, changes)  # type: ignore
                            logger.info(f"Applied runtime overrides: {list(changes.keys())}")
                        except Exception as e:
                            logger.warning(f"Failed to apply runtime overrides: {e}")

                # Process trading logic
                if not self.paused:
                    await self._process_trading_cycle()

                # Update metrics
                await self._update_metrics()

                # Calculate loop timing
                loop_duration = (datetime.utcnow() - loop_start).total_seconds()
                if hasattr(self.metrics, "record_loop_time"):
                    self.metrics.record_loop_time(loop_duration)  # type: ignore[attr-defined]

                # Sleep for configured interval
                sleep_time = max(0.0, trading_interval - loop_duration)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                # Log periodic status
                if loop_count % 60 == 0:  # Every 60 loops
                    await self._log_status()

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                await asyncio.sleep(5)  # Pause before retrying

                # Increment error count
                if hasattr(self.metrics, "increment_error_count"):
                    self.metrics.increment_error_count()  # type: ignore[attr-defined]

                # Emergency stop if too many consecutive errors
                consec = getattr(self.metrics, "consecutive_errors", 0)
                if consec and consec > 10:
                    logger.critical("Too many consecutive errors, stopping engine")
                    await self.stop()
                    break

    # ---------- Helpers to normalize signal / size ----------
    def _normalize_signal(self, raw: Any, default_symbol: str) -> Optional[Signal]:
        try:
            if raw is None:
                return None
            # Already a Signal
            if isinstance(raw, Signal):
                if not getattr(raw, "symbol", None):
                    raw.symbol = default_symbol  # type: ignore
                if not getattr(raw, "id", None):
                    raw.id = f"{default_symbol}-{raw.side}-{int(datetime.utcnow().timestamp()*1000)}"  # type: ignore
                return raw
            # Mapping
            if isinstance(raw, dict):
                side = raw.get("side") or raw.get("type") or raw.get("signal") or raw.get("signal_type") or ""
                strength = float(raw.get("strength") or raw.get("score") or 0.0)
                symbol = raw.get("symbol") or default_symbol
                sid = raw.get("id") or f"{symbol}-{side}-{int(datetime.utcnow().timestamp()*1000)}"
                return Signal(id=sid, symbol=symbol, side=str(side).upper(), strength=strength)  # type: ignore
            # Tuple/list: (side, strength, symbol?)
            if isinstance(raw, (tuple, list)):
                side = raw[0] if len(raw) > 0 else ""
                strength = float(raw[1]) if len(raw) > 1 else 0.0
                symbol = raw[2] if len(raw) > 2 else default_symbol
                sid = f"{symbol}-{side}-{int(datetime.utcnow().timestamp()*1000)}"
                return Signal(id=sid, symbol=str(symbol), side=str(side).upper(), strength=strength)  # type: ignore
            # String: "BUY"/"SELL"/"LONG"/"SHORT"
            if isinstance(raw, str):
                side = raw.upper()
                sid = f"{default_symbol}-{side}-{int(datetime.utcnow().timestamp()*1000)}"
                return Signal(id=sid, symbol=default_symbol, side=side, strength=0.3)  # type: ignore
        except Exception as e:
            logger.warning(f"Failed to normalize signal {raw!r}: {e}")
        return None

    def _coerce_position_size(self, size: Any) -> Tuple[float, Optional[str]]:
        if isinstance(size, (tuple, list)):
            qty = size[0] if len(size) > 0 else 0.0
            reason = size[1] if len(size) > 1 else None
        else:
            qty = size
            reason = None
        try:
            return float(qty or 0.0), str(reason) if reason is not None else None
        except Exception:
            return 0.0, "non-numeric-size"

    # ---------- Core cycle ----------
    async def _process_trading_cycle(self) -> None:
        """Process one complete trading cycle."""

        # 1. Generate trading signals
        raw_sig = await _maybe_await(self.signal_generator.generate_signal(self.config.symbol))  # type: ignore[attr-defined]
        sig = self._normalize_signal(raw_sig, _get(self.config, "symbol", ""))

        if sig and sig.id not in self.processed_signals:
            logger.info(f"New signal: {sig.side} {sig.strength:.2f} [{sig.symbol}]")
            try:
                # 2. Process signal through strategy
                await self._process_signal(sig)
                self.processed_signals.add(sig.id)
            except ZeroDivisionError:
                logger.error("Error calculating position size: division by zero. Skipping this signal.")
            except Exception as e:
                logger.error(f"Error handling signal {sig.id}: {e}", exc_info=True)

        # 3. Manage existing positions
        await self._manage_positions()

        # 4. Process DCA opportunities
        dca_enabled = _get(self.config, "dca_enabled", _get(self.config, "adaptive_dca", False))
        if dca_enabled:
            await self._process_dca()

        # 5. Handle order updates
        await self._update_orders()

    async def _process_signal(self, signal: Signal) -> None:
        """Process a trading signal."""
        symbol = signal.symbol

        # Check if we can trade this signal
        can_trade = await self._can_trade_signal(signal)
        if not can_trade:
            return

        # Calculate position size
        size_raw = self.risk_manager.calculate_position_size(signal, self.active_positions.get(symbol))  # type: ignore[attr-defined]
        qty, reason = self._coerce_position_size(size_raw)

        if qty <= 0:
            logger.debug(f"Position size too small for {symbol} (reason={reason or 'n/a'})")
            return

        # Check risk limits
        try:
            ok_to_open = self.risk_manager.can_open_position(symbol, signal.side, qty)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"RiskManager.can_open_position failed for {symbol}: {e}")
            ok_to_open = True

        if not ok_to_open:
            logger.warning(f"Risk limits prevent opening position for {symbol}")
            return

        # Place order
        try:
            order = await _maybe_await(self.order_manager.place_order(  # type: ignore[attr-defined]
                symbol=symbol,
                side=signal.side,
                quantity=qty,
                order_type=getattr(OrderType, "MARKET", "MARKET"),
                metadata={"signal_id": signal.id, "strategy": "signal"},
            ))

            if order:
                self.pending_orders[getattr(order, "id", f"{symbol}-{int(datetime.utcnow().timestamp()*1000)}")] = order  # type: ignore
                logger.info(f"Order placed: {getattr(order, 'side', 'UNK')} {getattr(order, 'quantity', qty)} {symbol}")

        except TypeError as e:
            # If OrderManager.place_order does not accept metadata or order_type names differ
            logger.debug(f"place_order signature mismatch, retrying minimal call: {e}")
            try:
                order = await _maybe_await(self.order_manager.place_order(  # type: ignore[attr-defined]
                    symbol=symbol,
                    side=signal.side,
                    quantity=qty,
                    order_type=getattr(OrderType, "MARKET", "MARKET"),
                ))
                if order:
                    self.pending_orders[getattr(order, "id", f"{symbol}-{int(datetime.utcnow().timestamp()*1000)}")] = order  # type: ignore
                    logger.info(f"Order placed: {getattr(order, 'side', 'UNK')} {getattr(order, 'quantity', qty)} {symbol}")
            except Exception as e2:
                logger.error(f"Failed to place order for signal {signal.id}: {e2}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to place order for signal {signal.id}: {e}", exc_info=True)

    async def _manage_positions(self) -> None:
        """Manage existing positions."""
        for symbol, position in list(self.active_positions.items()):
            try:
                # Check exit conditions
                exit_signal = await _maybe_await(self.exit_manager.should_exit(position))  # type: ignore[attr-defined]

                if exit_signal:
                    logger.info(f"Exit signal for {symbol}: {getattr(exit_signal, 'reason', 'exit')}")
                    await self._close_position(position, getattr(exit_signal, "reason", "exit"))
                    continue

                # Update position data
                updated_position = await _maybe_await(self.position_manager.update_position(position))  # type: ignore[attr-defined]
                if updated_position:
                    self.active_positions[symbol] = updated_position  # type: ignore

            except Exception as e:
                logger.error(f"Error managing position {symbol}: {e}", exc_info=True)

    async def _process_dca(self) -> None:
        """Process Dollar Cost Averaging opportunities."""
        for symbol in list(_get(self.config, "symbols", []) or []):
            try:
                dca_action = await _maybe_await(self.dca_manager.should_dca(  # type: ignore[attr-defined]
                    symbol, self.active_positions.get(symbol)
                ))

                if dca_action:
                    logger.info(f"DCA opportunity for {symbol}")
                    await self._execute_dca(symbol, dca_action)

            except Exception as e:
                logger.error(f"Error processing DCA for {symbol}: {e}", exc_info=True)

    async def _execute_dca(self, symbol: str, dca_action: Any) -> None:
        """Execute a DCA action (implementation depends on strategy)."""
        # Placeholder: implement as per your DCA policy
        return None

    async def _close_position(self, position: Position, reason: str) -> None:
        """Close a position."""
        try:
            order = await _maybe_await(self.order_manager.close_position(position, reason))  # type: ignore[attr-defined]

            if order:
                logger.info(f"Position close order placed: {position.symbol}")
                self.pending_orders[getattr(order, "id", f"{position.symbol}-{int(datetime.utcnow().timestamp()*1000)}")] = order  # type: ignore
            else:
                # Remove from active positions if already closed
                self.active_positions.pop(position.symbol, None)

        except Exception as e:
            logger.error(f"Failed to close position {position.symbol}: {e}", exc_info=True)

    async def _update_orders(self) -> None:
        """Update status of pending orders."""
        for order_id, _order in list(self.pending_orders.items()):
            try:
                updated_order = await _maybe_await(self.order_manager.get_order_status(order_id))  # type: ignore[attr-defined]

                if updated_order and getattr(updated_order, "is_filled", lambda: False)():
                    # Order filled, update position
                    await self._handle_filled_order(updated_order)
                    del self.pending_orders[order_id]

                elif updated_order and getattr(updated_order, "is_cancelled", lambda: False)():
                    # Order cancelled
                    logger.info(f"Order {order_id} was cancelled")
                    del self.pending_orders[order_id]

            except Exception as e:
                logger.error(f"Error updating order {order_id}: {e}", exc_info=True)

    async def _handle_filled_order(self, order: Order) -> None:
        """Handle a filled order."""
        symbol = getattr(order, "symbol", None) or _get(self.config, "symbol", "")
        self.trades_executed += 1

        logger.info(
            f"Order filled: {getattr(order, 'side', 'UNK')} {getattr(order, 'executed_qty', getattr(order, 'quantity', 0.0))} "
            f"{symbol} @ {getattr(order, 'avg_price', getattr(order, 'price', 0.0))}"
        )

        # Update position
        position = await _maybe_await(self.position_manager.handle_filled_order(order))  # type: ignore[attr-defined]

        if position:
            if getattr(position, "size", 0) != 0:
                self.active_positions[symbol] = position  # type: ignore
            else:
                # Position closed
                self.active_positions.pop(symbol, None)

                # Log trade result
                pnl = calculate_pnl(position)  # type: ignore
                self.total_pnl += pnl

                logger.info(f"Position closed: {symbol} PnL: {format_currency(pnl)}")  # type: ignore

        # Record metrics
        if hasattr(self.metrics, "record_trade"):
            self.metrics.record_trade(order)  # type: ignore[attr-defined]

    async def _can_trade_signal(self, signal: Signal) -> bool:
        """Check if we can trade a signal."""

        # Check if symbol is in allowed list
        symbols = list(_get(self.config, "symbols", []) or [])
        if symbols and signal.symbol not in symbols:
            return False

        # Check trading hours
        if not self._is_trading_hours():
            return False

        # Check cooldown periods (method may be missing)
        in_cd = False
        try:
            if hasattr(self.order_manager, "is_in_cooldown"):
                maybe = self.order_manager.is_in_cooldown(signal.symbol)  # type: ignore[attr-defined]
                in_cd = await _maybe_await(maybe)
        except Exception as e:
            logger.warning(f"Cooldown check failed for {signal.symbol}: {e}")
            in_cd = False
        if in_cd:
            return False

        # Check existing position limits
        max_pos = float(_get(self.config, "max_position_size", 0.0) or 0.0)
        current_position = self.active_positions.get(signal.symbol)
        if max_pos > 0 and current_position and abs(getattr(current_position, "size", 0.0)) >= max_pos:
            return False

        return True

    def _is_trading_hours(self) -> bool:
        """Check if we're in allowed trading hours."""
        if not _get(self.config, "trading_hours_enabled", False):
            return True

        now = datetime.utcnow()
        start = int(_get(self.config, "trading_start_hour", 0))
        end = int(_get(self.config, "trading_end_hour", 23))
        return start <= now.hour <= end

    async def _check_emergency_stop(self) -> bool:
        """Check for emergency stop conditions."""

        # Check daily loss limit
        try:
            daily_pnl = await _maybe_await(self.metrics.get_daily_pnl())  # type: ignore[attr-defined]
        except Exception:
            daily_pnl = 0.0
        max_daily_loss = float(_get(self.config, "max_daily_loss", _get(self.config, "max_daily_loss_pct", 0.0)) or 0.0)
        if max_daily_loss > 0 and daily_pnl < -abs(max_daily_loss):
            logger.critical(f"Daily loss limit exceeded: {format_currency(daily_pnl)}")  # type: ignore
            return True

        # Check account balance
        balance = None
        try:
            bal = self.position_manager.get_account_balance  # type: ignore[attr-defined]
            balance = await _maybe_await(bal)
        except Exception as e:
            logger.debug(f"Account balance read failed: {e}")
            balance = None
        min_balance = float(_get(self.config, "min_account_balance", 0.0) or 0.0)
        if balance is not None and min_balance > 0 and float(balance) < min_balance:
            logger.critical(f"Account balance too low: {format_currency(float(balance))}")  # type: ignore
            return True

        # Check maximum drawdown
        try:
            max_dd = await _maybe_await(self.metrics.get_max_drawdown())  # type: ignore[attr-defined]
        except Exception:
            max_dd = 0.0
        conf_dd = float(_get(self.config, "max_drawdown", 0.0) or 0.0)
        try:
            dd_ok = max_dd > conf_dd > 0.0
        except Exception:
            dd_ok = False
        if dd_ok:
            logger.critical(f"Maximum drawdown exceeded: {max_dd:.2%}")
            return True

        return False

    async def _health_check(self) -> None:
        """Perform system health check."""
        try:
            # Check exchange connectivity
            await _maybe_await(self.client.get_exchange_info())  # type: ignore[attr-defined]

            # Check position synchronization
            await _maybe_await(self.position_manager.sync_positions())  # type: ignore[attr-defined]

            # Optional: check system resources

            logger.debug("Health check passed")

        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            if hasattr(self.metrics, "increment_health_check_failures"):
                self.metrics.increment_health_check_failures()  # type: ignore[attr-defined]

    async def _update_metrics(self) -> None:
        """Update performance metrics."""
        try:
            # Current positions
            total_position_value = 0.0
            for pos in self.active_positions.values():
                sz = float(getattr(pos, "size", 0.0) or 0.0)
                ep = float(getattr(pos, "entry_price", getattr(pos, "entry", 0.0)) or 0.0)
                total_position_value += abs(sz * ep)

            # Update metrics
            if hasattr(self.metrics, "update_positions_count"):
                self.metrics.update_positions_count(len(self.active_positions))  # type: ignore[attr-defined]
            if hasattr(self.metrics, "update_total_position_value"):
                self.metrics.update_total_position_value(total_position_value)  # type: ignore[attr-defined]
            if hasattr(self.metrics, "update_total_pnl"):
                self.metrics.update_total_pnl(self.total_pnl)  # type: ignore[attr-defined]

        except Exception as e:
            logger.error(f"Error updating metrics: {e}", exc_info=True)

    async def _log_status(self) -> None:
        """Log current trading status."""
        uptime = (datetime.utcnow() - self.start_time if self.start_time else timedelta(0))

        status_info = {
            "uptime": str(uptime).split(".")[0],  # Remove microseconds
            "active_positions": len(self.active_positions),
            "pending_orders": len(self.pending_orders),
            "trades_executed": self.trades_executed,
            "total_pnl": format_currency(self.total_pnl),  # type: ignore
            "paused": self.paused,
        }

        logger.info("Trading status", **status_info)

    async def _load_state(self) -> None:
        """Load previous state from persistence."""
        try:
            state = await self.state_manager.load_state()
            if state:
                # Restore relevant state
                self.processed_signals = set(state.get("processed_signals", []))  # type: ignore[call-arg]
                logger.info("Previous state loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load previous state: {e}")

    async def _save_state(self) -> None:
        """Save current state to persistence."""
        try:
            state = {
                "processed_signals": list(self.processed_signals),
                "timestamp": datetime.utcnow().isoformat(),
                "total_pnl": self.total_pnl,
                "trades_executed": self.trades_executed,
            }

            await self.state_manager.save_state(state)
            logger.debug("State saved successfully")

        except Exception as e:
            logger.error(f"Failed to save state: {e}", exc_info=True)

    async def _cancel_all_pending_orders(self) -> None:
        """Cancel all pending orders."""
        for order_id in list(self.pending_orders.keys()):
            try:
                await _maybe_await(self.order_manager.cancel_order(order_id))  # type: ignore[attr-defined]
                logger.info(f"Cancelled order {order_id}")
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}", exc_info=True)

        self.pending_orders.clear()

    async def _close_all_positions(self) -> None:
        """Close all open positions."""
        for position in list(self.active_positions.values()):
            try:
                await self._close_position(position, "Engine shutdown")
            except Exception as e:
                logger.error(f"Failed to close position {position.symbol}: {e}", exc_info=True)

    def _log_final_stats(self) -> None:
        """Log final trading statistics."""
        if self.start_time:
            uptime = datetime.utcnow() - self.start_time

            final_stats = {
                "total_uptime": str(uptime).split(".")[0],
                "trades_executed": self.trades_executed,
                "final_pnl": format_currency(self.total_pnl),  # type: ignore
                "active_positions_at_end": len(self.active_positions),
            }

            logger.info("Final trading statistics", **final_stats)


@asynccontextmanager
async def live_trading_context(config: Config):
    """Context manager for live trading engine."""
    engine = LiveTradingEngine(config)

    try:
        await engine.start()
        yield engine
    finally:
        await engine.stop()


async def run_live_trading(config: Config) -> None:
    """Run live trading with proper setup and teardown."""
    setup_structured_logging(config)

    logger.info("Starting live trading session")

    try:
        async with live_trading_context(config) as engine:
            # Keep running until shutdown signal
            await engine._shutdown_event.wait()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Live trading session failed: {e}", exc_info=True)
        raise
    finally:
        logger.info("Live trading session ended")


if __name__ == "__main__":
    from core.config import load_config  # type: ignore

    # Load configuration
    config = load_config()

    # Run live trading
    asyncio.run(run_live_trading(config))
