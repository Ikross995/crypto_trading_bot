"""
Risk management system for trading operations.

Handles position sizing, portfolio risk limits, drawdown protection,
and various risk control mechanisms.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.types import Position, Signal
from exchange.client import BinanceClient

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk management limits configuration."""

    # Position sizing
    max_position_size_usd: float = 1000.0
    max_position_pct_of_account: float = 10.0  # % of account balance
    risk_per_trade_pct: float = 1.0  # Risk per individual trade

    # Portfolio limits
    max_total_exposure_pct: float = 50.0  # Max % of account exposed
    max_positions_per_symbol: int = 1
    max_total_positions: int = 10
    max_correlation_exposure: float = 30.0  # Max exposure to correlated assets

    # Loss limits
    max_daily_loss_pct: float = 5.0
    max_daily_loss_usd: float | None = None
    max_weekly_loss_pct: float = 10.0
    max_monthly_loss_pct: float = 20.0
    max_drawdown_pct: float = 15.0

    # Consecutive loss protection
    max_consecutive_losses: int = 5
    loss_streak_reduction_factor: float = 0.5  # Reduce size after streak

    # Volatility adjustments
    volatility_lookback_days: int = 20
    max_volatility_multiplier: float = 2.0
    min_volatility_multiplier: float = 0.5


@dataclass
class RiskMetrics:
    """Current risk metrics state."""

    # Account metrics
    account_balance: float = 0.0
    total_exposure: float = 0.0
    available_margin: float = 0.0

    # Position metrics
    active_positions: int = 0
    total_unrealized_pnl: float = 0.0
    largest_position_size: float = 0.0

    # Loss tracking
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    consecutive_losses: int = 0

    # Risk ratios
    exposure_ratio: float = 0.0  # Total exposure / Account balance
    margin_utilization: float = 0.0
    risk_adjusted_return: float = 0.0


class RiskManager:
    """
    Comprehensive risk management system.

    Features:
    - Dynamic position sizing based on account balance and volatility
    - Portfolio-level risk limits and exposure management
    - Drawdown protection and loss limits
    - Correlation-based exposure limits
    - Volatility-adjusted position sizing
    - Risk metrics monitoring and alerts
    """

    def __init__(
        self, client: BinanceClient, limits: RiskLimits | None = None
    ):
        self.client = client
        self.limits = limits or RiskLimits()

        # Current state
        self.metrics = RiskMetrics()
        self.positions: dict[str, Position] = {}
        self.daily_trades: list[dict] = []

        # Performance tracking
        self.equity_curve: list[tuple[datetime, float]] = []
        self.peak_equity = 0.0
        self.last_update = datetime.now()

        # Risk state
        self.trading_enabled = True
        self.risk_alerts: list[str] = []

    def update_account_info(self) -> bool:
        """Update account balance and margin information."""

        try:
            account_info = self.client.get_account_info()

            if account_info:
                self.metrics.account_balance = float(
                    account_info.get("totalWalletBalance", 0)
                )
                self.metrics.available_margin = float(
                    account_info.get("availableBalance", 0)
                )
                self.metrics.total_exposure = float(
                    account_info.get("totalPositionInitialMargin", 0)
                )

                # Update ratios
                if self.metrics.account_balance > 0:
                    self.metrics.exposure_ratio = (
                        self.metrics.total_exposure / self.metrics.account_balance
                    )
                    self.metrics.margin_utilization = (
                        self.metrics.account_balance - self.metrics.available_margin
                    ) / self.metrics.account_balance

                # Update equity curve
                current_equity = (
                    self.metrics.account_balance + self.metrics.total_unrealized_pnl
                )
                self.equity_curve.append((datetime.now(), current_equity))

                # Update peak and drawdown
                if current_equity > self.peak_equity:
                    self.peak_equity = current_equity

                if self.peak_equity > 0:
                    self.metrics.current_drawdown = (
                        (self.peak_equity - current_equity) / self.peak_equity * 100
                    )
                    self.metrics.max_drawdown = max(
                        self.metrics.max_drawdown, self.metrics.current_drawdown
                    )

                logger.debug(
                    f"Updated account info: Balance={self.metrics.account_balance}, "
                    f"Exposure={self.metrics.total_exposure}, Drawdown={self.metrics.current_drawdown:.2f}%"
                )

                return True
            else:
                logger.error("Failed to get account information")
                return False

        except Exception as e:
            logger.error(f"Error updating account info: {e}")
            return False

    def update_positions(self, positions: dict[str, Position]):
        """Update current positions for risk calculation."""

        self.positions = positions
        self.metrics.active_positions = len(positions)

        # Calculate position metrics
        total_unrealized = 0.0
        largest_position = 0.0

        for position in positions.values():
            total_unrealized += position.unrealized_pnl
            position_value = abs(position.quantity * position.entry_price)
            largest_position = max(largest_position, position_value)

        self.metrics.total_unrealized_pnl = total_unrealized
        self.metrics.largest_position_size = largest_position

        # Update P&L tracking
        self._update_pnl_tracking()

    def calculate_position_size(
        self, symbol: str, signal: Signal, stop_loss_price: float | None = None
    ) -> tuple[float, dict[str, Any]]:
        """
        Calculate optimal position size based on risk management rules.

        Args:
            symbol: Trading symbol
            signal: Trading signal with entry price
            stop_loss_price: Stop loss price for risk calculation

        Returns:
            Tuple of (position_size, calculation_details)
        """

        calculation = {
            "base_size": 0.0,
            "risk_adjusted_size": 0.0,
            "volatility_adjusted_size": 0.0,
            "final_size": 0.0,
            "risk_amount": 0.0,
            "adjustments": [],
            "blocked": False,
            "reason": "",
        }

        try:
            # Check if trading is enabled
            if not self.trading_enabled:
                calculation["blocked"] = True
                calculation["reason"] = "Trading disabled due to risk limits"
                return 0.0, calculation

            # Check position limits
            if not self._check_position_limits(symbol):
                calculation["blocked"] = True
                calculation["reason"] = "Position limits exceeded"
                return 0.0, calculation

            # Check loss limits
            if not self._check_loss_limits():
                calculation["blocked"] = True
                calculation["reason"] = "Daily/weekly loss limits exceeded"
                return 0.0, calculation

            # Calculate base position size
            entry_price = signal.price

            if stop_loss_price:
                # Risk-based sizing
                risk_amount = self.metrics.account_balance * (
                    self.limits.risk_per_trade_pct / 100
                )
                price_risk = abs(entry_price - stop_loss_price)
                base_size = risk_amount / price_risk if price_risk > 0 else 0

                calculation["risk_amount"] = risk_amount
                calculation["base_size"] = base_size
            else:
                # Fixed percentage of account
                max_position_value = self.metrics.account_balance * (
                    self.limits.max_position_pct_of_account / 100
                )
                base_size = max_position_value / entry_price
                calculation["base_size"] = base_size

            # Apply risk adjustments
            risk_adjusted_size = self._apply_risk_adjustments(
                base_size, symbol, calculation
            )
            calculation["risk_adjusted_size"] = risk_adjusted_size

            # Apply volatility adjustments
            volatility_adjusted_size = self._apply_volatility_adjustment(
                risk_adjusted_size, symbol, calculation
            )
            calculation["volatility_adjusted_size"] = volatility_adjusted_size

            # Apply hard limits
            final_size = self._apply_hard_limits(
                volatility_adjusted_size, entry_price, calculation
            )
            calculation["final_size"] = final_size

            logger.info(
                f"Calculated position size for {symbol}: {final_size} "
                f"(Risk: {calculation['risk_amount']:.2f} USD)"
            )

            return final_size, calculation

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            calculation["blocked"] = True
            calculation["reason"] = f"Calculation error: {e}"
            return 0.0, calculation

    def _check_position_limits(self, symbol: str) -> bool:
        """Check if new position would violate position limits."""

        # Max positions per symbol
        symbol_positions = len(
            [p for p in self.positions.values() if p.symbol == symbol]
        )
        if symbol_positions >= self.limits.max_positions_per_symbol:
            logger.warning(
                f"Max positions per symbol exceeded for {symbol}: {symbol_positions}"
            )
            return False

        # Max total positions
        if self.metrics.active_positions >= self.limits.max_total_positions:
            logger.warning(
                f"Max total positions exceeded: {self.metrics.active_positions}"
            )
            return False

        # Max exposure
        if self.metrics.exposure_ratio >= (self.limits.max_total_exposure_pct / 100):
            logger.warning(f"Max exposure exceeded: {self.metrics.exposure_ratio:.2%}")
            return False

        return True

    def _check_loss_limits(self) -> bool:
        """Check if current losses exceed limits."""

        # Daily loss limit
        if self.limits.max_daily_loss_usd:
            if self.metrics.daily_pnl <= -self.limits.max_daily_loss_usd:
                logger.warning(f"Daily loss limit exceeded: {self.metrics.daily_pnl}")
                return False

        daily_loss_pct = (
            abs(self.metrics.daily_pnl) / self.metrics.account_balance * 100
        )
        if (
            self.metrics.daily_pnl < 0
            and daily_loss_pct >= self.limits.max_daily_loss_pct
        ):
            logger.warning(f"Daily loss percentage exceeded: {daily_loss_pct:.2f}%")
            return False

        # Weekly loss limit
        weekly_loss_pct = (
            abs(self.metrics.weekly_pnl) / self.metrics.account_balance * 100
        )
        if (
            self.metrics.weekly_pnl < 0
            and weekly_loss_pct >= self.limits.max_weekly_loss_pct
        ):
            logger.warning(f"Weekly loss percentage exceeded: {weekly_loss_pct:.2f}%")
            return False

        # Max drawdown limit
        if self.metrics.current_drawdown >= self.limits.max_drawdown_pct:
            logger.warning(
                f"Max drawdown exceeded: {self.metrics.current_drawdown:.2f}%"
            )
            return False

        return True

    def _apply_risk_adjustments(
        self, base_size: float, symbol: str, calculation: dict
    ) -> float:
        """Apply various risk adjustments to position size."""

        adjusted_size = base_size

        # Consecutive loss adjustment
        if self.metrics.consecutive_losses >= self.limits.max_consecutive_losses:
            reduction = self.limits.loss_streak_reduction_factor
            adjusted_size *= reduction
            calculation["adjustments"].append(
                f"Consecutive loss reduction: {reduction:.2f}"
            )

        # Drawdown adjustment
        if self.metrics.current_drawdown > 5.0:  # Start reducing at 5% drawdown
            reduction = max(0.5, 1.0 - (self.metrics.current_drawdown / 100))
            adjusted_size *= reduction
            calculation["adjustments"].append(f"Drawdown reduction: {reduction:.2f}")

        # Exposure adjustment
        if self.metrics.exposure_ratio > 0.3:  # Reduce if high exposure
            reduction = max(0.7, 1.0 - self.metrics.exposure_ratio)
            adjusted_size *= reduction
            calculation["adjustments"].append(f"Exposure reduction: {reduction:.2f}")

        return adjusted_size

    def _apply_volatility_adjustment(
        self, size: float, symbol: str, calculation: dict
    ) -> float:
        """Apply volatility-based position sizing adjustment."""

        try:
            # Get recent volatility data (simplified)
            # In practice, you'd get this from your data fetcher
            historical_vol = self._get_symbol_volatility(symbol)

            if historical_vol > 0:
                # Adjust size based on volatility (higher vol = smaller size)
                vol_multiplier = min(
                    self.limits.max_volatility_multiplier,
                    max(self.limits.min_volatility_multiplier, 1.0 / historical_vol),
                )

                adjusted_size = size * vol_multiplier
                calculation["adjustments"].append(
                    f"Volatility adjustment: {vol_multiplier:.2f}"
                )

                return adjusted_size

        except Exception as e:
            logger.warning(f"Error calculating volatility adjustment: {e}")

        return size

    def _apply_hard_limits(
        self, size: float, entry_price: float, calculation: dict
    ) -> float:
        """Apply hard position size limits."""

        # Max position size in USD
        max_size_by_usd = self.limits.max_position_size_usd / entry_price
        if size > max_size_by_usd:
            size = max_size_by_usd
            calculation["adjustments"].append(
                f"USD limit applied: {self.limits.max_position_size_usd}"
            )

        # Max position as percentage of account
        max_size_by_pct = (
            self.metrics.account_balance * self.limits.max_position_pct_of_account / 100
        ) / entry_price
        if size > max_size_by_pct:
            size = max_size_by_pct
            calculation["adjustments"].append(
                f"Account % limit applied: {self.limits.max_position_pct_of_account}%"
            )

        # Minimum position size (avoid dust trades)
        min_size = 10.0 / entry_price  # Minimum $10 position
        if size < min_size:
            size = 0.0  # Block trade if too small
            calculation["adjustments"].append("Below minimum position size")

        return size

    def _get_symbol_volatility(self, symbol: str) -> float:
        """Get recent volatility for symbol (simplified calculation)."""

        try:
            # This would typically use your data fetcher to get recent prices
            # For now, return a default volatility estimate
            return 1.0  # Neutral volatility multiplier

        except Exception as e:
            logger.warning(f"Error getting volatility for {symbol}: {e}")
            return 1.0

    def _update_pnl_tracking(self):
        """Update daily/weekly/monthly P&L tracking."""

        try:
            now = datetime.now()

            # Calculate realized + unrealized P&L for different periods
            # This is simplified - in practice you'd track trades and periods more precisely

            # Daily P&L (reset at start of each day)
            if now.date() != self.last_update.date():
                self.metrics.daily_pnl = 0.0  # Reset daily tracking
                self._check_consecutive_losses()

            # Add current unrealized to daily P&L
            self.metrics.daily_pnl += self.metrics.total_unrealized_pnl

            self.last_update = now

        except Exception as e:
            logger.error(f"Error updating P&L tracking: {e}")

    def _check_consecutive_losses(self):
        """Check and update consecutive loss counter."""

        # Check if yesterday was a loss
        if self.metrics.daily_pnl < 0:
            self.metrics.consecutive_losses += 1
        else:
            self.metrics.consecutive_losses = 0

    def check_emergency_stop(self) -> tuple[bool, str]:
        """Check if trading should be immediately stopped."""

        # Critical drawdown
        if self.metrics.current_drawdown >= self.limits.max_drawdown_pct:
            return True, f"Critical drawdown: {self.metrics.current_drawdown:.2f}%"

        # Critical daily loss
        daily_loss_pct = (
            abs(self.metrics.daily_pnl) / self.metrics.account_balance * 100
        )
        if (
            self.metrics.daily_pnl < 0
            and daily_loss_pct >= self.limits.max_daily_loss_pct * 0.8
        ):
            return True, f"Approaching daily loss limit: {daily_loss_pct:.2f}%"

        # Account balance too low
        if self.metrics.account_balance < 100:  # Minimum balance threshold
            return True, "Account balance below minimum threshold"

        # Margin call risk
        if self.metrics.margin_utilization > 0.9:
            return (
                True,
                f"High margin utilization: {self.metrics.margin_utilization:.1%}",
            )

        return False, ""

    def enable_trading(self):
        """Enable trading (remove risk blocks)."""
        self.trading_enabled = True
        logger.info("Trading enabled by risk manager")

    def disable_trading(self, reason: str):
        """Disable trading due to risk concerns."""
        self.trading_enabled = False
        self.risk_alerts.append(f"{datetime.now()}: Trading disabled - {reason}")
        logger.warning(f"Trading disabled by risk manager: {reason}")

    def get_risk_summary(self) -> dict[str, Any]:
        """Get comprehensive risk management summary."""

        return {
            "trading_enabled": self.trading_enabled,
            "account_balance": self.metrics.account_balance,
            "total_exposure": self.metrics.total_exposure,
            "exposure_ratio": self.metrics.exposure_ratio,
            "active_positions": self.metrics.active_positions,
            "daily_pnl": self.metrics.daily_pnl,
            "weekly_pnl": self.metrics.weekly_pnl,
            "current_drawdown": self.metrics.current_drawdown,
            "max_drawdown": self.metrics.max_drawdown,
            "consecutive_losses": self.metrics.consecutive_losses,
            "margin_utilization": self.metrics.margin_utilization,
            "largest_position": self.metrics.largest_position_size,
            "risk_alerts": self.risk_alerts[-10:],  # Last 10 alerts
            "limits": {
                "max_daily_loss_pct": self.limits.max_daily_loss_pct,
                "max_drawdown_pct": self.limits.max_drawdown_pct,
                "max_positions": self.limits.max_total_positions,
                "max_exposure_pct": self.limits.max_total_exposure_pct,
                "risk_per_trade_pct": self.limits.risk_per_trade_pct,
            },
        }

    def get_position_recommendations(self) -> dict[str, Any]:
        """Get recommendations for current positions."""

        recommendations = {
            "reduce_positions": [],
            "close_positions": [],
            "warnings": [],
        }

        # Check each position
        for symbol, position in self.positions.items():
            position_value = abs(position.quantity * position.entry_price)
            position_pct = position_value / self.metrics.account_balance * 100

            # Large position warning
            if position_pct > self.limits.max_position_pct_of_account:
                recommendations["reduce_positions"].append(
                    {
                        "symbol": symbol,
                        "current_pct": position_pct,
                        "reason": "Position size exceeds limit",
                    }
                )

            # Underwater position with high risk
            if position.unrealized_pnl < 0:
                loss_pct = abs(position.unrealized_pnl) / position_value * 100
                if loss_pct > 10:  # 10% loss
                    recommendations["close_positions"].append(
                        {
                            "symbol": symbol,
                            "loss_pct": loss_pct,
                            "reason": "High unrealized loss",
                        }
                    )

        # Overall portfolio warnings
        if self.metrics.exposure_ratio > 0.8:
            recommendations["warnings"].append(
                "High portfolio exposure - consider reducing positions"
            )

        if self.metrics.current_drawdown > 10:
            recommendations["warnings"].append(
                "Significant drawdown - consider defensive positioning"
            )

        return recommendations
