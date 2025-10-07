#!/usr/bin/env python3
"""
Backtesting Engine

Historical strategy testing with comprehensive performance analysis.
Tests trading strategies on historical data to validate effectiveness.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from loguru import logger
from strategy.exits import ExitManager

from core.config import Config
from core.constants import OrderSide, OrderType, Timeframe
from core.types import BacktestResult, Order, Position, Signal, Trade
from core.utils import format_currency
from data.fetchers import HistoricalDataFetcher
from data.indicators import TechnicalIndicators
from data.preprocessing import FeatureEngineer
from infra.logging import setup_structured_logging
from strategy.dca import DCAManager
from strategy.risk import RiskManager
from strategy.signals import SignalGenerator


@dataclass
class BacktestConfig:
    """Configuration for backtesting runs."""

    start_date: datetime
    end_date: datetime
    initial_balance: float
    commission: float = 0.001  # 0.1% commission
    slippage: float = 0.0005  # 0.05% slippage
    symbol: str = "BTCUSDT"
    timeframe: Timeframe = Timeframe.M5

    # Strategy parameters
    enable_dca: bool = True
    max_positions: int = 1
    risk_per_trade: float = 0.02  # 2% per trade


class BacktestEngine:
    """
    Comprehensive backtesting engine for strategy validation.

    Features:
    - Historical data replay
    - Realistic order execution simulation
    - Commission and slippage modeling
    - Detailed performance analysis
    - Risk metrics calculation
    - Strategy optimization support
    """

    def __init__(self, config: Config, backtest_config: BacktestConfig):
        self.config = config
        self.bt_config = backtest_config

        # Data components
        self.data_fetcher = HistoricalDataFetcher(config)
        self.indicator_calc = TechnicalIndicators()
        self.feature_engineer = FeatureEngineer()

        # Strategy components
        self.signal_generator = SignalGenerator(config)
        self.risk_manager = RiskManager(config)
        self.exit_manager = ExitManager(config)
        self.dca_manager = DCAManager(config) if backtest_config.enable_dca else None

        # Backtest state
        self.current_time: datetime | None = None
        self.current_data: pd.DataFrame | None = None
        self.current_balance = backtest_config.initial_balance
        self.initial_balance = backtest_config.initial_balance

        # Position and order tracking
        self.active_positions: dict[str, Position] = {}
        self.pending_orders: list[Order] = []
        self.completed_trades: list[Trade] = []

        # Performance tracking
        self.balance_history: list[tuple[datetime, float]] = []
        self.equity_curve: list[float] = []
        self.drawdown_curve: list[float] = []
        self.peak_balance = backtest_config.initial_balance

        # Statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.total_commission = 0.0
        self.max_drawdown = 0.0

        logger.info(
            "Backtest engine initialized",
            symbol=backtest_config.symbol,
            start_date=backtest_config.start_date.isoformat(),
            end_date=backtest_config.end_date.isoformat(),
            initial_balance=format_currency(backtest_config.initial_balance),
        )

    async def run_backtest(self) -> BacktestResult:
        """Run complete backtesting process."""
        logger.info("Starting backtesting process...")

        start_time = datetime.utcnow()

        try:
            # 1. Load and prepare historical data
            await self._prepare_data()

            # 2. Initialize strategy components
            await self._initialize_strategy()

            # 3. Run simulation
            await self._run_simulation()

            # 4. Calculate final metrics
            result = self._calculate_results()

            # 5. Log summary
            self._log_backtest_summary(result)

            execution_time = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Backtesting completed in {execution_time:.2f} seconds")

            return result

        except Exception as e:
            logger.error(f"Backtesting failed: {e}", exc_info=True)
            raise

    async def _prepare_data(self) -> None:
        """Load and prepare historical data for backtesting."""
        logger.info("Preparing historical data...")

        # Fetch historical price data
        raw_data = await self.data_fetcher.fetch_historical_data(
            symbol=self.bt_config.symbol,
            timeframe=self.bt_config.timeframe,
            start_time=self.bt_config.start_date,
            end_time=self.bt_config.end_date,
        )

        if raw_data.empty:
            raise ValueError("No historical data available for the specified period")

        logger.info(f"Loaded {len(raw_data)} data points")

        # Calculate technical indicators
        data_with_indicators = self.indicator_calc.calculate_all_indicators(raw_data)

        # Engineer features
        self.current_data = self.feature_engineer.engineer_features(
            data_with_indicators
        )

        logger.info("Data preparation completed")

    async def _initialize_strategy(self) -> None:
        """Initialize strategy components with historical data."""
        logger.info("Initializing strategy components...")

        # Initialize signal generator with historical data
        await self.signal_generator.initialize(historical_data=self.current_data)

        logger.info("Strategy initialization completed")

    async def _run_simulation(self) -> None:
        """Run the main simulation loop."""
        logger.info("Running backtesting simulation...")

        data_length = len(self.current_data)

        # Start from a reasonable lookback period (e.g., 100 periods)
        start_index = max(100, self.signal_generator.min_lookback_periods)

        for i in range(start_index, data_length):
            try:
                # Set current time and price data
                current_row = self.current_data.iloc[i]
                self.current_time = current_row.name  # Index should be datetime

                # Get current market data slice for strategies
                lookback_data = self.current_data.iloc[
                    max(0, i - 200) : i + 1
                ]  # Last 200 periods

                # Process pending orders first
                await self._process_pending_orders(current_row)

                # Generate trading signal
                signal = await self._generate_signal(lookback_data, current_row)

                if signal:
                    await self._process_signal(signal, current_row)

                # Manage existing positions
                await self._manage_positions(current_row)

                # Process DCA if enabled
                if self.dca_manager:
                    await self._process_dca(current_row)

                # Update balance history
                current_balance = self._calculate_current_balance(current_row)
                self.balance_history.append((self.current_time, current_balance))

                # Update equity curve and drawdown
                self.equity_curve.append(current_balance)

                if current_balance > self.peak_balance:
                    self.peak_balance = current_balance

                drawdown = (self.peak_balance - current_balance) / self.peak_balance
                self.drawdown_curve.append(drawdown)

                if drawdown > self.max_drawdown:
                    self.max_drawdown = drawdown

                # Progress logging
                if i % 1000 == 0:
                    progress = (i - start_index) / (data_length - start_index) * 100
                    logger.debug(
                        f"Simulation progress: {progress:.1f}% "
                        f"({self.current_time}, Balance: {format_currency(current_balance)})"
                    )

            except Exception as e:
                logger.error(f"Error in simulation at index {i}: {e}")
                continue

        logger.info("Simulation completed")

    async def _generate_signal(
        self, lookback_data: pd.DataFrame, current_row: pd.Series
    ) -> Signal | None:
        """Generate trading signal for current time."""
        try:
            # Use signal generator with lookback data
            signal = await self.signal_generator.generate_signal_from_data(
                symbol=self.bt_config.symbol,
                data=lookback_data,
                current_time=self.current_time,
            )

            return signal

        except Exception as e:
            logger.debug(f"Error generating signal at {self.current_time}: {e}")
            return None

    async def _process_signal(self, signal: Signal, current_row: pd.Series) -> None:
        """Process a trading signal."""
        symbol = signal.symbol
        current_price = current_row["close"]

        # Check if we can trade this signal
        if not self._can_trade_signal(signal):
            return

        # Calculate position size
        position_size = self._calculate_position_size(signal, current_price)

        if position_size <= 0:
            return

        # Create and place order
        order = Order(
            id=f"order_{len(self.pending_orders) + len(self.completed_trades)}",
            symbol=symbol,
            side=signal.side,
            order_type=OrderType.MARKET,
            quantity=position_size,
            price=current_price,
            status="NEW",
            timestamp=self.current_time,
            metadata={"signal_id": signal.id, "strategy": "signal"},
        )

        # Simulate market order execution
        filled_order = self._execute_market_order(order, current_row)

        if filled_order:
            await self._handle_filled_order(filled_order, current_row)
            logger.debug(
                f"Order executed: {filled_order.side} {filled_order.executed_qty} "
                f"{symbol} @ {filled_order.avg_price}"
            )

    def _execute_market_order(
        self, order: Order, current_row: pd.Series
    ) -> Order | None:
        """Simulate market order execution with slippage and commission."""

        # Calculate execution price with slippage
        base_price = current_row["close"]
        slippage_factor = self.bt_config.slippage

        if order.side == OrderSide.BUY:
            execution_price = base_price * (1 + slippage_factor)
        else:
            execution_price = base_price * (1 - slippage_factor)

        # Check if we have sufficient balance for buy orders
        trade_value = order.quantity * execution_price
        commission = trade_value * self.bt_config.commission

        if order.side == OrderSide.BUY:
            required_balance = trade_value + commission
            if required_balance > self.current_balance:
                logger.debug(
                    f"Insufficient balance for buy order: "
                    f"need {format_currency(required_balance)}, "
                    f"have {format_currency(self.current_balance)}"
                )
                return None

        # Fill the order
        order.status = "FILLED"
        order.executed_qty = order.quantity
        order.avg_price = execution_price
        order.fill_timestamp = self.current_time
        order.commission = commission

        return order

    async def _handle_filled_order(self, order: Order, current_row: pd.Series) -> None:
        """Handle a filled order and update positions."""
        symbol = order.symbol

        # Update balance
        trade_value = order.executed_qty * order.avg_price
        commission = order.commission or 0

        if order.side == OrderSide.BUY:
            self.current_balance -= trade_value + commission
        else:
            self.current_balance += trade_value - commission

        self.total_commission += commission

        # Update or create position
        current_position = self.active_positions.get(symbol)

        if current_position:
            if order.side == current_position.side:
                # Adding to position
                total_size = current_position.size + order.executed_qty
                total_cost = (
                    current_position.size * current_position.entry_price
                    + order.executed_qty * order.avg_price
                )
                new_avg_price = total_cost / total_size

                current_position.size = total_size
                current_position.entry_price = new_avg_price
            else:
                # Reducing or closing position
                if order.executed_qty >= abs(current_position.size):
                    # Position closed or reversed
                    pnl = self._calculate_position_pnl(
                        current_position, order.avg_price
                    )

                    # Create trade record
                    trade = Trade(
                        id=f"trade_{self.total_trades}",
                        symbol=symbol,
                        side=current_position.side,
                        entry_price=current_position.entry_price,
                        exit_price=order.avg_price,
                        quantity=abs(current_position.size),
                        pnl=pnl - commission,  # Include commission in P&L
                        entry_time=current_position.entry_time,
                        exit_time=self.current_time,
                        strategy="backtest",
                    )

                    self.completed_trades.append(trade)
                    self.total_trades += 1
                    self.total_pnl += trade.pnl

                    if trade.pnl > 0:
                        self.winning_trades += 1
                    else:
                        self.losing_trades += 1

                    # Remove or update position
                    remaining_qty = order.executed_qty - abs(current_position.size)
                    if remaining_qty > 0:
                        # Position reversed
                        current_position.side = order.side
                        current_position.size = remaining_qty
                        current_position.entry_price = order.avg_price
                        current_position.entry_time = self.current_time
                    else:
                        # Position closed
                        del self.active_positions[symbol]
                else:
                    # Position reduced
                    current_position.size -= order.executed_qty
        else:
            # Create new position
            position = Position(
                symbol=symbol,
                side=order.side,
                size=order.executed_qty,
                entry_price=order.avg_price,
                entry_time=self.current_time,
                current_price=order.avg_price,
            )
            self.active_positions[symbol] = position

    def _calculate_position_pnl(self, position: Position, exit_price: float) -> float:
        """Calculate P&L for a position."""
        if position.side == OrderSide.BUY:
            return (exit_price - position.entry_price) * position.size
        else:
            return (position.entry_price - exit_price) * abs(position.size)

    async def _manage_positions(self, current_row: pd.Series) -> None:
        """Manage existing positions."""
        for symbol, position in list(self.active_positions.items()):
            try:
                current_price = current_row["close"]
                position.current_price = current_price

                # Check exit conditions
                exit_signal = await self.exit_manager.should_exit(position)

                if exit_signal:
                    await self._close_position(
                        position, current_row, exit_signal.reason
                    )

            except Exception as e:
                logger.error(f"Error managing position {symbol}: {e}")

    async def _close_position(
        self, position: Position, current_row: pd.Series, reason: str
    ) -> None:
        """Close a position."""
        # Create close order
        close_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY

        order = Order(
            id=f"close_{len(self.completed_trades)}",
            symbol=position.symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=abs(position.size),
            price=current_row["close"],
            status="NEW",
            timestamp=self.current_time,
            metadata={"strategy": "exit", "reason": reason},
        )

        # Execute close order
        filled_order = self._execute_market_order(order, current_row)

        if filled_order:
            await self._handle_filled_order(filled_order, current_row)

    async def _process_dca(self, current_row: pd.Series) -> None:
        """Process DCA opportunities."""
        if not self.dca_manager:
            return

        for symbol in [self.bt_config.symbol]:  # Focus on main symbol for backtest
            try:
                position = self.active_positions.get(symbol)
                dca_action = await self.dca_manager.should_dca(symbol, position)

                if dca_action:
                    # Simple DCA implementation for backtesting
                    current_price = current_row["close"]
                    dca_size = (
                        position.size * 0.3
                        if position
                        else self._calculate_base_position_size(current_price)
                    )

                    order = Order(
                        id=f"dca_{len(self.completed_trades)}",
                        symbol=symbol,
                        side=position.side if position else OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=dca_size,
                        price=current_price,
                        status="NEW",
                        timestamp=self.current_time,
                        metadata={"strategy": "dca"},
                    )

                    filled_order = self._execute_market_order(order, current_row)
                    if filled_order:
                        await self._handle_filled_order(filled_order, current_row)

            except Exception as e:
                logger.error(f"Error processing DCA for {symbol}: {e}")

    async def _process_pending_orders(self, current_row: pd.Series) -> None:
        """Process any pending limit orders (simplified for backtesting)."""
        # For backtesting, we primarily use market orders
        # This method is here for future enhancement
        pass

    def _can_trade_signal(self, signal: Signal) -> bool:
        """Check if we can trade a signal."""

        # Check if we already have a position in this symbol
        if signal.symbol in self.active_positions:
            current_position = self.active_positions[signal.symbol]
            # Don't open opposite position (for simplicity)
            if current_position.side != signal.side:
                return False

        # Check maximum positions limit
        if len(self.active_positions) >= self.bt_config.max_positions:
            return False

        return True

    def _calculate_position_size(self, signal: Signal, current_price: float) -> float:
        """Calculate position size for the signal."""
        # Use fixed risk per trade
        risk_amount = self.current_balance * self.bt_config.risk_per_trade

        # For simplicity, assume 2% stop loss
        stop_loss_distance = current_price * 0.02

        if stop_loss_distance == 0:
            return 0

        position_size = risk_amount / stop_loss_distance

        # Ensure we don't use more than available balance
        max_position_value = self.current_balance * 0.8  # Use max 80% of balance
        max_position_size = max_position_value / current_price

        return min(position_size, max_position_size)

    def _calculate_base_position_size(self, current_price: float) -> float:
        """Calculate base position size for DCA."""
        return (self.current_balance * 0.1) / current_price  # 10% of balance

    def _calculate_current_balance(self, current_row: pd.Series) -> float:
        """Calculate current total balance including unrealized P&L."""
        unrealized_pnl = 0
        current_price = current_row["close"]

        for position in self.active_positions.values():
            position.current_price = current_price
            unrealized_pnl += self._calculate_position_pnl(position, current_price)

        return self.current_balance + unrealized_pnl

    def _calculate_results(self) -> BacktestResult:
        """Calculate comprehensive backtest results."""

        final_balance = (
            self.equity_curve[-1] if self.equity_curve else self.initial_balance
        )
        total_return = (
            (final_balance - self.initial_balance) / self.initial_balance
        ) * 100

        # Trading statistics
        win_rate = (self.winning_trades / max(1, self.total_trades)) * 100
        avg_win = sum(t.pnl for t in self.completed_trades if t.pnl > 0) / max(
            1, self.winning_trades
        )
        avg_loss = sum(t.pnl for t in self.completed_trades if t.pnl < 0) / max(
            1, self.losing_trades
        )
        profit_factor = abs(avg_win * self.winning_trades) / max(
            1, abs(avg_loss * self.losing_trades)
        )

        # Calculate Sharpe ratio (simplified)
        if len(self.equity_curve) > 1:
            returns = pd.Series(self.equity_curve).pct_change().dropna()
            sharpe_ratio = (
                returns.mean() / max(returns.std(), 0.001) * (365**0.5)
            )  # Annualized
        else:
            sharpe_ratio = 0

        # Create result object
        result = BacktestResult(
            start_date=self.bt_config.start_date,
            end_date=self.bt_config.end_date,
            initial_balance=self.initial_balance,
            final_balance=final_balance,
            total_return=total_return,
            total_pnl=self.total_pnl,
            max_drawdown=self.max_drawdown,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=self.total_trades,
            winning_trades=self.winning_trades,
            losing_trades=self.losing_trades,
            avg_win=avg_win,
            avg_loss=avg_loss,
            total_commission=self.total_commission,
            equity_curve=self.equity_curve.copy(),
            drawdown_curve=self.drawdown_curve.copy(),
            trades=self.completed_trades.copy(),
            balance_history=self.balance_history.copy(),
        )

        return result

    def _log_backtest_summary(self, result: BacktestResult) -> None:
        """Log comprehensive backtest summary."""

        duration = result.end_date - result.start_date

        summary = {
            "period": f"{result.start_date.strftime('%Y-%m-%d')} to {result.end_date.strftime('%Y-%m-%d')}",
            "duration": f"{duration.days} days",
            "initial_balance": format_currency(result.initial_balance),
            "final_balance": format_currency(result.final_balance),
            "total_return": f"{result.total_return:+.2f}%",
            "total_pnl": format_currency(result.total_pnl),
            "max_drawdown": f"{result.max_drawdown:.2%}",
            "sharpe_ratio": f"{result.sharpe_ratio:.2f}",
            "total_trades": result.total_trades,
            "win_rate": f"{result.win_rate:.1f}%",
            "profit_factor": f"{result.profit_factor:.2f}",
            "avg_win": format_currency(result.avg_win),
            "avg_loss": format_currency(result.avg_loss),
            "total_commission": format_currency(result.total_commission),
        }

        logger.info("=== BACKTESTING RESULTS ===")
        for key, value in summary.items():
            logger.info(f"{key.replace('_', ' ').title()}: {value}")
        logger.info("========================")


async def run_backtest(
    config: Config, backtest_config: BacktestConfig
) -> BacktestResult:
    """Run a complete backtesting session."""
    setup_structured_logging(config)

    logger.info("Starting backtesting session")

    engine = BacktestEngine(config, backtest_config)

    try:
        result = await engine.run_backtest()
        return result

    except Exception as e:
        logger.error(f"Backtesting failed: {e}", exc_info=True)
        raise
    finally:
        logger.info("Backtesting session ended")


if __name__ == "__main__":
    import asyncio

    from core.config import load_config

    # Load configuration
    config = load_config()

    # Create backtest configuration
    backtest_config = BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 12, 31),
        initial_balance=10000.0,
        symbol="BTCUSDT",
        timeframe=Timeframe.M15,
    )

    # Run backtest
    result = asyncio.run(run_backtest(config, backtest_config))

    print("\nBacktest completed!")
    print(f"Total Return: {result.total_return:+.2f}%")
    print(f"Max Drawdown: {result.max_drawdown:.2%}")
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"Win Rate: {result.win_rate:.1f}%")
