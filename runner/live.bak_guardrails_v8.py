#!/usr/bin/env python3
"""
Live Trading Engine

Handles real money trading with comprehensive safety measures,
position management, and risk controls.
"""

import asyncio
import signal
import inspect
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from loguru import logger

try:
    from infra.settings import RuntimeOverridesWatcher, apply_settings_to_config
except Exception:
    class RuntimeOverridesWatcher:
        def __init__(self, path: str):
            self.path = path
        def poll(self):
            return {}
    def apply_settings_to_config(config, changes):
        try:
            for k, v in (changes or {}).items():
                if hasattr(config, k):
                    setattr(config, k, v)
        except Exception:
            pass
from infra.logging import setup_structured_logging
from infra.metrics import MetricsCollector
from infra.persistence import StateManager

from core.config import Config
from core.constants import OrderType
from core.types import Order, Position, Signal
from core.utils import calculate_pnl, format_currency

from exchange.client import BinanceClient
from exchange.orders import OrderManager
from exchange.positions import PositionManager

from strategy.exits import ExitManager
from strategy.dca import DCAManager
from strategy.risk import RiskManager
from strategy.signals import SignalGenerator


class LiveTradingEngine:
    """
    Live trading execution engine with guardrails.

    Safe points:
    - DRY_RUN skips exchange init/sync
    - Runtime overrides watcher is optional (safe stubs)
    - Risk sizing accepts both number and (qty, stop) tuple
    - Cooldown fallback if OrderManager has no is_in_cooldown
    - Emergency checks are tolerant to missing fields
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = logger  # use module logger
        self.running = False
        self.paused = False
        self._shutdown_event = asyncio.Event()

        # Runtime overrides watcher (optional)
        self._overrides_watcher = None
        try:
            path = getattr(self.config, "overrides_path", "") or "config/overrides.txt"
            if os.path.exists(path):
                self._overrides_watcher = RuntimeOverridesWatcher(path)
        except Exception:
            self._overrides_watcher = None

        # Core components
        self.client = BinanceClient(testnet=getattr(config, "testnet", False))
        self.order_manager = OrderManager(self.client)
        self.position_manager = PositionManager(self.client)

        # Strategy components
        self.signal_generator = SignalGenerator(config)
        self.risk_manager = RiskManager(config)
        self.exit_manager = ExitManager(config)
        self.dca_manager = DCAManager(config)

        # Infra
        self.metrics = MetricsCollector(config)
        self.state_manager = StateManager(config)

        # State
        self.active_positions = {}   # symbol -> Position
        self.pending_orders = {}     # id -> Order
        self.processed_signals = set()
        self._cooldown_until = {}    # symbol -> datetime

        # Perf
        self.start_time = None
        self.trades_executed = 0
        self.total_pnl = 0.0

        logger.info("Live trading engine initialized", symbol=getattr(config, "symbol", ""), mode="LIVE")

    async def start(self) -> None:
        if self.running:
            logger.warning("Engine already running")
            return
        logger.info("Starting live trading engine...")
        try:
            await self._initialize_components()
            self._setup_signal_handlers()
            await self._load_state()
            self.running = True
            self.start_time = datetime.utcnow()
            logger.info("Live trading engine started successfully")
            await self._run_trading_loop()
        except Exception as e:
            logger.error(f"Failed to start live trading engine: {e}", exc_info=True)
            await self.stop()
            raise

    async def stop(self) -> None:
        if not self.running:
            return
        logger.info("Stopping live trading engine...")
        self.running = False
        self._shutdown_event.set()
        try:
            await self._cancel_all_pending_orders()
            await self._save_state()
            if getattr(self.config, "close_positions_on_exit", False):
                await self._close_all_positions()
            await self._shutdown_components()
            self._log_final_stats()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        logger.info("Live trading engine stopped")

    async def pause(self) -> None:
        self.paused = True
        logger.info("Trading paused - no new positions will be opened")

    async def resume(self) -> None:
        self.paused = False
        logger.info("Trading resumed")

    async def _initialize_components(self) -> None:
        logger.info("Initializing trading components...")
        # DRY_RUN must not touch real exchange / positions
        if getattr(self.config, "dry_run", False):
            logger.info("DRY_RUN: skipping exchange initialization and position sync")
        else:
            try:
                self.client.get_exchange_info()
            except Exception as e:
                logger.warning(f"Exchange info failed: {e}")
            try:
                await self.position_manager.initialize()
                positions = await self.position_manager.get_positions()
                for pos in positions or []:
                    try:
                        self.active_positions[pos.symbol] = pos
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Position manager init/sync failed: {e}")
        try:
            await self.signal_generator.initialize()
        except Exception as e:
            logger.warning(f"Signal generator init warning: {e}")
        await self.metrics.start()
        logger.info("All components initialized successfully")

    async def _shutdown_components(self) -> None:
        try:
            await self.metrics.stop()
        except Exception:
            pass
        try:
            await self.client.close()
        except Exception:
            pass

    def _setup_signal_handlers(self) -> None:
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            try:
                asyncio.get_event_loop().create_task(self.stop())
            except RuntimeError:
                # no running loop - ignore
                pass
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except Exception:
            # not all platforms allow this
            pass

    async def _run_trading_loop(self) -> None:
        logger.info("Starting main trading loop")
        loop_count = 0
        last_health_check = datetime.utcnow()
        sleep_seconds = float(getattr(self.config, "loop_sleep_sec", 1.0))
        if sleep_seconds <= 0:
            sleep_seconds = 1.0

        while self.running:
            try:
                loop_count += 1
                now = datetime.utcnow()

                # periodic health check
                if (now - last_health_check) > timedelta(minutes=5):
                    await self._health_check()
                    last_health_check = now

                # emergency stop
                if await self._check_emergency_stop():
                    logger.critical("Emergency stop triggered!")
                    await self.stop()
                    break

                # runtime overrides
                if self._overrides_watcher:
                    try:
                        changes = self._overrides_watcher.poll() or {}
                        if changes:
                            apply_settings_to_config(self.config, changes)
                            logger.info("Applied runtime overrides: %s", list(changes.keys()))
                    except Exception as e:
                        logger.warning(f"Overrides watcher error: {e}")

                # trading
                if not self.paused:
                    await self._process_trading_cycle()

                # metrics
                await self._update_metrics()

                if loop_count % 60 == 0:
                    await self._log_status()

                await asyncio.sleep(sleep_seconds)

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                try:
                    self.metrics.increment_error_count()
                    if getattr(self.metrics, "consecutive_errors", 0) > 10:
                        logger.critical("Too many consecutive errors, stopping engine")
                        await self.stop()
                        break
                except Exception:
                    pass
                await asyncio.sleep(1.0)

    async def _process_trading_cycle(self) -> None:
        # 1) get signal for first configured symbol (or config.symbol)
        sym = getattr(self.config, "symbol", None)
        symbols = getattr(self.config, "symbols", []) or ([sym] if sym else [])
        base_symbol = symbols[0] if symbols else (sym or "")

        try:
            sig = await self.signal_generator.generate_signal(base_symbol)
        except Exception as e:
            logger.warning(f"Signal generation failed: {e}")
            sig = None

        if sig and getattr(sig, "id", None) not in self.processed_signals:
            s_sym = getattr(sig, "symbol", None) or base_symbol
            s_side = getattr(sig, "side", "")
            s_strength = float(getattr(sig, "strength", 0.0) or 0.0)
            logger.info("New signal: %s %.2f [%s]", s_side, s_strength, s_sym)
            await self._process_signal(sig)
            self.processed_signals.add(getattr(sig, "id", f"sig-{int(time.time()*1000)}"))

        # 2) manage positions
        await self._manage_positions()

        # 3) DCA (adaptive_dca is also acceptable flag)
        if getattr(self.config, "dca_enabled", False) or getattr(self.config, "adaptive_dca", False):
            await self._process_dca()

        # 4) update orders
        await self._update_orders()

    async def _process_signal(self, signal: Signal) -> None:
        symbol = getattr(signal, "symbol", None) or getattr(self.config, "symbol", None)
        if not symbol:
            symbols = getattr(self.config, "symbols", [])
            if symbols:
                symbol = symbols[0]
        if not symbol:
            return

        # can trade?
        if not await self._can_trade_signal(signal):
            return

        # sizing (tuple or number)
        try:
            sz = self.risk_manager.calculate_position_size(signal, self.active_positions.get(symbol))
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return

        stop_hint = None
        if isinstance(sz, (tuple, list)):
            position_size = float(sz[0]) if len(sz) > 0 else 0.0
            if len(sz) > 1:
                try:
                    stop_hint = float(sz[1])
                except Exception:
                    stop_hint = None
        else:
            try:
                position_size = float(sz or 0.0)
            except Exception:
                position_size = 0.0

        if position_size <= 0:
            logger.debug(f"Position size too small for {symbol}")
            return

        # risk limits (if available)
        can_open = True
        if hasattr(self.risk_manager, "can_open_position"):
            try:
                can_open = bool(self.risk_manager.can_open_position(symbol, getattr(signal, "side", ""), position_size))
            except Exception:
                can_open = True
        if not can_open:
            logger.warning(f"Risk limits prevent opening position for {symbol}")
            return

        # place market order
        try:
            order = await self.order_manager.place_order(
                symbol=symbol,
                side=getattr(signal, "side", ""),
                quantity=position_size,
                order_type=OrderType.MARKET,
                metadata={"signal_id": getattr(signal, "id", ""), "strategy": "signal"},
            )
            if order:
                oid = getattr(order, "id", None) or f"order-{int(time.time()*1000)}"
                self.pending_orders[oid] = order
                # set local cooldown fallback
                try:
                    cd = int(getattr(self.config, "cooldown_sec", 0) or 0)
                    if cd > 0:
                        self._cooldown_until[str(symbol)] = datetime.utcnow() + timedelta(seconds=cd)
                except Exception:
                    pass
                logger.info("Order placed: %s %s %s", getattr(order, "side", ""), getattr(order, "quantity", position_size), symbol)
        except Exception as e:
            logger.error(f"Failed to place order for signal {getattr(signal, 'id', '')}: {e}")

    async def _manage_positions(self) -> None:
        for symbol, position in list(self.active_positions.items()):
            try:
                exit_signal = await self.exit_manager.should_exit(position)
                if exit_signal:
                    logger.info(f"Exit signal for {symbol}: {getattr(exit_signal, 'reason', '')}")
                    await self._close_position(position, getattr(exit_signal, "reason", "exit"))
                    continue
                updated_position = await self.position_manager.update_position(position)
                if updated_position:
                    self.active_positions[symbol] = updated_position
            except Exception as e:
                logger.error(f"Error managing position {symbol}: {e}")

    async def _process_dca(self) -> None:
        for symbol in getattr(self.config, "symbols", []) or []:
            try:
                dca_action = await self.dca_manager.should_dca(symbol, self.active_positions.get(symbol))
                if dca_action:
                    logger.info(f"DCA opportunity for {symbol}")
                    await self._execute_dca(symbol, dca_action)
            except Exception as e:
                logger.error(f"Error processing DCA for {symbol}: {e}")

    async def _execute_dca(self, symbol: str, dca_action) -> None:
        # Implement if needed by your strategy
        pass

    async def _close_position(self, position: Position, reason: str) -> None:
        try:
            order = await self.order_manager.close_position(position, reason)
            if order:
                oid = getattr(order, "id", None) or f"close-{int(time.time()*1000)}"
                logger.info(f"Position close order placed: {position.symbol}")
                self.pending_orders[oid] = order
            else:
                self.active_positions.pop(position.symbol, None)
        except Exception as e:
            logger.error(f"Failed to close position {position.symbol}: {e}")

    async def _update_orders(self) -> None:
        for order_id, _order in list(self.pending_orders.items()):
            try:
                updated_order = await self.order_manager.get_order_status(order_id)
                if updated_order and hasattr(updated_order, "is_filled") and updated_order.is_filled():
                    await self._handle_filled_order(updated_order)
                    self.pending_orders.pop(order_id, None)
                elif updated_order and hasattr(updated_order, "is_cancelled") and updated_order.is_cancelled():
                    logger.info(f"Order {order_id} was cancelled")
                    self.pending_orders.pop(order_id, None)
            except Exception as e:
                logger.error(f"Error updating order {order_id}: {e}")

    async def _handle_filled_order(self, order: Order) -> None:
        symbol = getattr(order, "symbol", "")
        self.trades_executed += 1
        logger.info("Order filled: %s %s %s @ %s", getattr(order, "side", ""), getattr(order, "executed_qty", 0), symbol, getattr(order, "avg_price", 0))
        try:
            position = await self.position_manager.handle_filled_order(order)
        except Exception as e:
            logger.error(f"handle_filled_order error: {e}")
            position = None

        if position:
            try:
                if getattr(position, "size", 0) != 0:
                    self.active_positions[symbol] = position
                else:
                    self.active_positions.pop(symbol, None)
                    pnl = calculate_pnl(position)
                    self.total_pnl += pnl
                    logger.info(f"Position closed: {symbol} PnL: {format_currency(pnl)}")
            except Exception:
                pass
        try:
            self.metrics.record_trade(order)
        except Exception:
            pass

    async def _can_trade_signal(self, signal: Signal) -> bool:
        symbol = getattr(signal, "symbol", "") or getattr(self.config, "symbol", "")
        if not symbol:
            return False
        allowed = getattr(self.config, "symbols", []) or [getattr(self.config, "symbol", "")]
        if symbol not in allowed:
            return False
        if not self._is_trading_hours():
            return False
        # cooldown (prefer OrderManager if present)
        try:
            fn = getattr(self.order_manager, "is_in_cooldown", None)
            if fn:
                res = fn(symbol)
                if asyncio.iscoroutine(res):
                    if await res:
                        return False
                else:
                    if res:
                        return False
            else:
                until = self._cooldown_until.get(symbol)
                if until and datetime.utcnow() < until:
                    return False
        except Exception:
            pass
        # max position size
        current_position = self.active_positions.get(symbol)
        try:
            max_pos = float(getattr(self.config, "max_position_size", 1e18))
            if current_position and abs(getattr(current_position, "size", 0.0)) >= max_pos:
                return False
        except Exception:
            pass
        return True

    def _is_trading_hours(self) -> bool:
        if not getattr(self.config, "trading_hours_enabled", False):
            return True
        now = datetime.utcnow().hour
        try:
            return int(getattr(self.config, "trading_start_hour", 0)) <= now <= int(getattr(self.config, "trading_end_hour", 23))
        except Exception:
            return True

    async def _get_account_balance(self) -> float:
        try:
            fn = getattr(self.position_manager, "get_account_balance", None)
            if not fn:
                return 0.0
            res = fn()
            if asyncio.iscoroutine(res):
                res = await res
            return float(res or 0.0)
        except Exception:
            return 0.0

    async def _check_emergency_stop(self) -> bool:
        # skip emergency stop checks in DRY_RUN
        if getattr(self.config, "dry_run", False):
            return False
        try:
            daily_pnl = 0.0
            try:
                daily_pnl = float(await self.metrics.get_daily_pnl())
            except Exception:
                daily_pnl = 0.0
            max_daily_loss = float(getattr(self.config, "max_daily_loss", 0.0))
            if daily_pnl < -abs(max_daily_loss):
                logger.critical(f"Daily loss limit exceeded: {format_currency(daily_pnl)}")
                return True

            balance = await self._get_account_balance()
            min_balance = float(getattr(self.config, "min_account_balance", 0.0))
            if min_balance > 0.0 and balance < min_balance:
                logger.critical(f"Account balance too low: {format_currency(balance)}")
                return True

            try:
                max_dd = float(getattr(self.config, "max_drawdown", 0.0))
                curr_dd = float(await self.metrics.get_max_drawdown())
                if max_dd > 0.0 and curr_dd > max_dd:
                    logger.critical(f"Maximum drawdown exceeded: {curr_dd:.2%}")
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    async def _health_check(self) -> None:
        try:
            self.client.get_exchange_info()
            try:
                await self.position_manager.sync_positions()
            except Exception:
                pass
            logger.debug("Health check passed")
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            try:
                self.metrics.increment_health_check_failures()
            except Exception:
                pass

    async def _update_metrics(self) -> None:
        try:
            total_position_value = 0.0
            for pos in list(self.active_positions.values()):
                try:
                    total_position_value += abs(float(getattr(pos, "size", 0.0)) * float(getattr(pos, "entry_price", 0.0)))
                except Exception:
                    pass
            self.metrics.update_positions_count(len(self.active_positions))
            self.metrics.update_total_position_value(total_position_value)
            self.metrics.update_total_pnl(self.total_pnl)
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")

    async def _log_status(self) -> None:
        uptime = (datetime.utcnow() - self.start_time) if self.start_time else timedelta(0)
        status_info = {
            "uptime": str(uptime).split(".")[0],
            "active_positions": len(self.active_positions),
            "pending_orders": len(self.pending_orders),
            "trades_executed": self.trades_executed,
            "total_pnl": format_currency(self.total_pnl),
            "paused": self.paused,
        }
        logger.info("Trading status", **status_info)

    async def _load_state(self) -> None:
        try:
            state = await self.state_manager.load_state()
            if state:
                self.processed_signals = set(state.get("processed_signals", []))
                logger.info("Previous state loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load previous state: {e}")

    async def _save_state(self) -> None:
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
            logger.error(f"Failed to save state: {e}")

    async def _cancel_all_pending_orders(self) -> None:
        for order_id in list(self.pending_orders.keys()):
            try:
                await self.order_manager.cancel_order(order_id)
                logger.info(f"Cancelled order {order_id}")
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}")
        self.pending_orders.clear()

    async def _close_all_positions(self) -> None:
        for position in list(self.active_positions.values()):
            try:
                await self._close_position(position, "Engine shutdown")
            except Exception as e:
                logger.error(f"Failed to close position {position.symbol}: {e}")

    def _log_final_stats(self) -> None:
        if self.start_time:
            uptime = datetime.utcnow() - self.start_time
            final_stats = {
                "total_uptime": str(uptime).split(".")[0],
                "trades_executed": self.trades_executed,
                "final_pnl": format_currency(self.total_pnl),
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
            await engine._shutdown_event.wait()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Live trading session failed: {e}", exc_info=True)
        raise
    finally:
        logger.info("Live trading session ended")


if __name__ == "__main__":
    from core.config import load_config
    cfg = load_config()
    asyncio.run(run_live_trading(cfg))
