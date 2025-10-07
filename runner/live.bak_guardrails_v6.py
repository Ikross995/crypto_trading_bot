#!/usr/bin/env python3
"""
Live Trading Engine

Handles real money trading with comprehensive safety measures,
position management, and risk controls.
"""

import asyncio
import signal
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from loguru import logger

from infra.settings import RuntimeOverridesWatcher, apply_settings_to_config
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
    Live trading execution engine with comprehensive safety measures.

    Features:
    - Real-time signal processing
    - Position and risk management
    - Emergency stop mechanisms
    - Performance monitoring
    - State persistence
    """

    def __init__(self, config: Config):
        self.config = config

        # Runtime overrides watcher (optional file path)
        self._overrides_watcher = None
        path = getattr(self.config, "overrides_path", "") or "config/overrides.txt"
        if os.path.exists(path):
            self._overrides_watcher = RuntimeOverridesWatcher(path)

        self.running = False
        self.paused = False
        self._shutdown_event = asyncio.Event()

        # Core components
        # (Не передаём неизвестные аргументы в BinanceClient, чтобы не словить
        # несовместимость сигнатуры.)
        self.client = BinanceClient()
        self.order_manager = OrderManager(self.client)
        self.position_manager = PositionManager(self.client)

        # Strategy components
        self.signal_generator = SignalGenerator(config)
        self.risk_manager = RiskManager(config)
        self.exit_manager = ExitManager(config)
        self.dca_manager = DCAManager(config)

        # Infrastructure
        self.metrics = MetricsCollector(config)
        self.state_manager = StateManager(config)

        # State tracking
        self.active_positions: dict[str, Position] = {}
        self.pending_orders: dict[str, Order] = {}
        self.processed_signals: set[str] = set()

        # Performance tracking
        self.start_time: datetime | None = None
        self.trades_executed = 0
        self.total_pnl = 0.0

        logger.info("Live trading engine initialized", mode="LIVE")

    async def start(self) -> None:
        """Start the live trading engine."""
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
        """Stop the trading engine gracefully."""
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
            logger.error(f"Error during shutdown: {e}", exc_info=True)

        logger.info("Live trading engine stopped")

    async def pause(self) -> None:
        self.paused = True
        logger.info("Trading paused - no new positions will be opened")

    async def resume(self) -> None:
        self.paused = False
        logger.info("Trading resumed")

    async def _initialize_components(self) -> None:
        """Initialize all trading components."""
        logger.info("Initializing trading components...")

        # Биржевые вызовы в DRY_RUN пропускаем, чтобы не ловить -1021/-1022
        try:
            if not getattr(self.config, "dry_run", False):
                self.client.get_exchange_info()
                await self.position_manager.initialize()
                positions = await self.position_manager.get_positions()
                for pos in positions or []:
                    self.active_positions[pos.symbol] = pos
            else:
                logger.info("DRY_RUN: skipping exchange initialization and position sync")
        except Exception as e:
            logger.warning(f"Exchange init/positions sync skipped due to error: {e}")

        # Инициализация генератора сигналов и метрик
        try:
            await self.signal_generator.initialize()
        except Exception as e:
            logger.warning(f"Signal generator init warning: {e}")

        await self.metrics.start()

        logger.info("All components initialized successfully")

    async def _shutdown_components(self) -> None:
        """Shutdown all components gracefully."""
        try:
            await self.metrics.stop()
        except Exception:
            pass
        try:
            # Не все клиенты имеют async close — оборачиваем в try.
            close = getattr(self.client, "close", None)
            if close:
                res = close()
                if asyncio.iscoroutine(res):
                    await res
        except Exception as e:
            logger.error(f"Error shutting down components: {e}")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""

        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            asyncio.create_task(self.stop())

        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except Exception:
            # Windows/threads: некоторые сигналы могут быть недоступны
            pass

    async def _run_trading_loop(self) -> None:
        """Main trading loop."""
        logger.info("Starting main trading loop")

        loop_count = 0
        last_health_check = datetime.utcnow()

        while self.running:
            try:
                loop_start = datetime.utcnow()
                loop_count += 1

                # Периодический health-check (каждые 5 минут)
                if (loop_start - last_health_check) > timedelta(minutes=5):
                    await self._health_check()
                    last_health_check = loop_start

                # Экстренные условия (DD, баланс, дневной лосс)
                if await self._check_emergency_stop():
                    logger.critical("Emergency stop triggered!")
                    await self.stop()
                    break

                # Рантайм‑оверрайды
                if self._overrides_watcher:
                    try:
                        changes = self._overrides_watcher.poll()
                        if changes:
                            apply_settings_to_config(self.config, changes)
                            logger.info("Applied runtime overrides: {}", list(changes.keys()))
                    except Exception as e:
                        logger.warning(f"Overrides watcher failed: {e}")

                # Торговая логика
                if not self.paused:
                    await self._process_trading_cycle()

                # Метрики
                await self._update_metrics()

                # Тайминг цикла
                loop_duration = (datetime.utcnow() - loop_start).total_seconds()
                self.metrics.record_loop_time(loop_duration)

                # Пауза между итерациями
                interval = float(getattr(self.config, "trading_interval", 1.0))
                sleep_time = max(0.0, interval - loop_duration)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                # Периодический статус
                if loop_count % 60 == 0:
                    await self._log_status()

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                await asyncio.sleep(5)
                self.metrics.increment_error_count()

                if getattr(self.metrics, "consecutive_errors", 0) > 10:
                    logger.critical("Too many consecutive errors, stopping engine")
                    await self.stop()
                    break

    async def _process_trading_cycle(self) -> None:
        """Process one complete trading cycle for all configured symbols."""
        symbols = getattr(self.config, "symbols", None) or [getattr(self.config, "symbol", "")]

        # 1) Генерация сигналов по каждому символу
        for sym in symbols:
            try:
                sig = await self.signal_generator.generate_signal(sym)
            except Exception as e:
                logger.warning(f"Signal generation failed for {sym}: {e}")
                sig = None

            if sig and sig.id not in self.processed_signals:
                logger.info(f"New signal: {sig.side} {getattr(sig, 'strength', 0.0):.2f} [{sym}]")
                await self._process_signal(sig)
                self.processed_signals.add(sig.id)

        # 2) Управление существующими позициями
        await self._manage_positions()

        # 3) DCA возможности
        if getattr(self.config, "dca_enabled", False):
            await self._process_dca()

        # 4) Апдейт ордеров
        await self._update_orders()

    async def _process_signal(self, signal: Signal) -> None:
        """Process a trading signal."""
        symbol = signal.symbol

        if not await self._can_trade_signal(signal):
            return

        position_size = self.risk_manager.calculate_position_size(
            signal, self.active_positions.get(symbol)
        )

        if position_size <= 0:
            logger.debug(f"Position size too small for {symbol}")
            return

        if not self.risk_manager.can_open_position(symbol, signal.side, position_size):
            logger.warning(f"Risk limits prevent opening position for {symbol}")
            return

        try:
            order = await self.order_manager.place_order(
                symbol=symbol,
                side=signal.side,
                quantity=position_size,
                order_type=OrderType.MARKET,
                metadata={"signal_id": signal.id, "strategy": "signal"},
            )
            if order:
                self.pending_orders[order.id] = order
                logger.info(f"Order placed: {order.side} {order.quantity} {symbol}")
        except Exception as e:
            logger.error(f"Failed to place order for signal {signal.id}: {e}")

    async def _manage_positions(self) -> None:
        """Manage existing positions."""
        for symbol, position in list(self.active_positions.items()):
            try:
                exit_signal = await self.exit_manager.should_exit(position)
                if exit_signal:
                    logger.info(f"Exit signal for {symbol}: {exit_signal.reason}")
                    await self._close_position(position, exit_signal.reason)
                    continue

                updated_position = await self.position_manager.update_position(position)
                if updated_position:
                    self.active_positions[symbol] = updated_position

            except Exception as e:
                logger.error(f"Error managing position {symbol}: {e}")

    async def _process_dca(self) -> None:
        """Process Dollar Cost Averaging opportunities."""
        for symbol in getattr(self.config, "symbols", []):
            try:
                dca_action = await self.dca_manager.should_dca(
                    symbol, self.active_positions.get(symbol)
                )
                if dca_action:
                    logger.info(f"DCA opportunity for {symbol}")
                    await self._execute_dca(symbol, dca_action)
            except Exception as e:
                logger.error(f"Error processing DCA for {symbol}: {e}")

    async def _execute_dca(self, symbol: str, dca_action) -> None:
        """Execute a DCA action (placeholder)."""
        # Реализация зависит от конкретной DCA-стратегии.
        return

    async def _close_position(self, position: Position, reason: str) -> None:
        """Close a position."""
        try:
            order = await self.order_manager.close_position(position, reason)
            if order:
                logger.info(f"Position close order placed: {position.symbol}")
                self.pending_orders[order.id] = order
            else:
                self.active_positions.pop(position.symbol, None)
        except Exception as e:
            logger.error(f"Failed to close position {position.symbol}: {e}")

    async def _update_orders(self) -> None:
        """Update status of pending orders."""
        for order_id, _order in list(self.pending_orders.items()):
            try:
                updated_order = await self.order_manager.get_order_status(order_id)

                if updated_order and updated_order.is_filled():
                    await self._handle_filled_order(updated_order)
                    del self.pending_orders[order_id]

                elif updated_order and updated_order.is_cancelled():
                    logger.info(f"Order {order_id} was cancelled")
                    del self.pending_orders[order_id]

            except Exception as e:
                logger.error(f"Error updating order {order_id}: {e}")

    async def _handle_filled_order(self, order: Order) -> None:
        """Handle a filled order."""
        symbol = order.symbol
        self.trades_executed += 1

        logger.info(f"Order filled: {order.side} {order.executed_qty} {symbol} @ {order.avg_price}")

        position = await self.position_manager.handle_filled_order(order)

        if position:
            if getattr(position, "size", 0) != 0:
                self.active_positions[symbol] = position
            else:
                # позиция закрыта
                self.active_positions.pop(symbol, None)
                pnl = calculate_pnl(position)
                self.total_pnl += pnl
                logger.info(f"Position closed: {symbol} PnL: {format_currency(pnl)}")

        self.metrics.record_trade(order)

    async def _can_trade_signal(self, signal: Signal) -> bool:
        """Check if we can trade a signal."""
        symbols = set(getattr(self.config, "symbols", []) or [])
        if symbols and signal.symbol not in symbols:
            return False

        if not self._is_trading_hours():
            return False

        # Кулдаун: если метода нет — просто пропускаем проверку
        try:
            fn = getattr(self.order_manager, "is_in_cooldown", None)
            if fn:
                in_cd = await fn(signal.symbol) if asyncio.iscoroutinefunction(fn) else fn(signal.symbol)
                if in_cd:
                    return False
        except Exception as e:
            logger.debug(f"Cooldown check failed: {e}")

        current_position = self.active_positions.get(signal.symbol)
        max_pos = float(getattr(self.config, "max_position_size", float("inf")))
        if current_position and abs(getattr(current_position, "size", 0.0)) >= max_pos:
            return False

        return True

    def _is_trading_hours(self) -> bool:
        """Check if we're in allowed trading hours."""
        if not getattr(self.config, "trading_hours_enabled", False):
            return True
        now = datetime.utcnow().hour
        start_h = int(getattr(self.config, "trading_start_hour", 0))
        end_h = int(getattr(self.config, "trading_end_hour", 23))
        return start_h <= now <= end_h

    async def _check_emergency_stop(self) -> bool:
        """Check for emergency stop conditions."""
        # Daily PnL
        try:
            daily_pnl = await self.metrics.get_daily_pnl()
        except Exception:
            daily_pnl = 0.0
        max_daily_loss = float(getattr(self.config, "max_daily_loss", float("inf")))
        if daily_pnl < -abs(max_daily_loss):
            logger.critical(f"Daily loss limit exceeded: {format_currency(daily_pnl)}")
            return True

        # Balance (если не удалось получить — не стопаемся)
        min_balance = float(getattr(self.config, "min_account_balance", 0.0))
        balance = float("inf")
        try:
            b = self.position_manager.get_account_balance()
            if isinstance(b, (int, float)):
                balance = float(b)
        except Exception as e:
            logger.warning(f"Balance check failed: {e}")
        if balance < min_balance:
            logger.critical(f"Account balance too low: {format_currency(balance)}")
            return True

        # Max drawdown
        try:
            max_drawdown = await self.metrics.get_max_drawdown()
        except Exception:
            max_drawdown = 0.0
        md_limit = float(getattr(self.config, "max_drawdown", 1.0))
        if max_drawdown > md_limit:
            logger.critical(f"Maximum drawdown exceeded: {max_drawdown:.2%}")
            return True

        return False

    async def _health_check(self) -> None:
        """Perform system health check."""
        try:
            if not getattr(self.config, "dry_run", False):
                self.client.get_exchange_info()
                await self.position_manager.sync_positions()
            logger.debug("Health check passed")
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            self.metrics.increment_health_check_failures()

    async def _update_metrics(self) -> None:
        """Update performance metrics."""
        try:
            total_position_value = sum(
                abs(getattr(pos, "size", 0.0) * getattr(pos, "entry_price", 0.0))
                for pos in self.active_positions.values()
            )
            self.metrics.update_positions_count(len(self.active_positions))
            self.metrics.update_total_position_value(total_position_value)
            self.metrics.update_total_pnl(self.total_pnl)
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")

    async def _log_status(self) -> None:
        """Log current trading status."""
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
        """Load previous state from persistence."""
        try:
            state = await self.state_manager.load_state()
            if state:
                self.processed_signals = set(state.get("processed_signals", []))
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
            logger.error(f"Failed to save state: {e}")

    async def _cancel_all_pending_orders(self) -> None:
        """Cancel all pending orders."""
        for order_id in list(self.pending_orders.keys()):
            try:
                await self.order_manager.cancel_order(order_id)
                logger.info(f"Cancelled order {order_id}")
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}")
        self.pending_orders.clear()

    async def _close_all_positions(self) -> None:
        """Close all open positions."""
        for position in list(self.active_positions.values()):
            try:
                await self._close_position(position, "Engine shutdown")
            except Exception as e:
                logger.error(f"Failed to close position {position.symbol}: {e}")

    def _log_final_stats(self) -> None:
        """Log final trading statistics."""
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
