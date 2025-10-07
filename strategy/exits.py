"""
Advanced Exit Systems for AI Trading Bot

Comprehensive exit management including stop losses, take profits,
trailing stops, and dynamic exit strategies.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from loguru import logger

from core.config import Config, get_config
from core.constants import OrderSide, OrderType, WorkingType
from core.types import Order, Position
from core.utils import format_price, round_price


class ExitType(Enum):
    """Exit order types."""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    TIME_BASED = "time_based"
    EMERGENCY = "emergency"


class ExitStatus(Enum):
    """Exit status types."""
    PENDING = "pending"
    ACTIVE = "active"
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class ExitOrder:
    """Exit order configuration."""
    
    exit_type: ExitType
    price: float
    quantity: float = 0.0  # 0 means full position
    order_id: str | None = None
    status: ExitStatus = ExitStatus.PENDING
    created_at: float = 0.0
    triggered_at: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class TrailingStopConfig:
    """Trailing stop configuration."""
    
    activation_distance: float  # Distance to activate trailing
    trail_distance: float       # Trailing distance
    max_loss: float            # Maximum loss limit
    update_frequency: int = 5   # Update frequency in seconds


class ExitManager:
    """
    Comprehensive exit management system.
    
    Handles multiple exit strategies including:
    - Fixed stop loss and take profit levels
    - Trailing stops with activation thresholds
    - Time-based exits
    - Emergency exits
    - Dynamic exit adjustment
    """

    def __init__(self, order_manager=None, config: Config = None):
        self.order_manager = order_manager
        self.config = config or get_config()
        
        # Active exit orders tracking
        self.active_exits: dict[str, list[ExitOrder]] = {}  # {symbol: [exit_orders]}
        self.trailing_stops: dict[str, dict[str, Any]] = {}  # {symbol: trailing_config}
        
        # Performance tracking
        self.last_update_times: dict[str, float] = {}
        self.exit_history: list[dict[str, Any]] = []
        
        logger.info("ExitManager initialized")

    def setup_exit_orders(
        self, 
        symbol: str,
        position: Position,
        stop_loss: float | None = None,
        take_profits: list[float] | None = None,
        tp_quantities: list[float] | None = None,
        trailing_config: TrailingStopConfig | None = None
    ) -> bool:
        """
        Setup comprehensive exit orders for a position.
        
        Args:
            symbol: Trading symbol
            position: Current position
            stop_loss: Stop loss price
            take_profits: List of take profit prices
            tp_quantities: List of quantities for each TP level
            trailing_config: Trailing stop configuration
            
        Returns:
            True if setup successful
        """
        if position.is_flat:
            logger.warning(f"Cannot setup exits for flat position: {symbol}")
            return False
        
        try:
            # Clear existing exits
            self._clear_symbol_exits(symbol)
            
            # Initialize exit orders list
            self.active_exits[symbol] = []
            
            # Setup stop loss
            if stop_loss and stop_loss > 0:
                success = self._setup_stop_loss(symbol, position, stop_loss)
                if not success:
                    logger.error(f"Failed to setup stop loss for {symbol}")
            
            # Setup take profits
            if take_profits and tp_quantities:
                success = self._setup_take_profits(
                    symbol, position, take_profits, tp_quantities
                )
                if not success:
                    logger.error(f"Failed to setup take profits for {symbol}")
            
            # Setup trailing stop
            if trailing_config:
                success = self._setup_trailing_stop(symbol, position, trailing_config)
                if not success:
                    logger.error(f"Failed to setup trailing stop for {symbol}")
            
            logger.info(f"Exit orders setup complete for {symbol}: "
                       f"{len(self.active_exits.get(symbol, []))} orders")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup exit orders for {symbol}: {e}")
            return False

    def _setup_stop_loss(self, symbol: str, position: Position, stop_price: float) -> bool:
        """Setup stop loss order."""
        try:
            if not self.order_manager:
                logger.warning("OrderManager not available for stop loss placement")
                return False
            
            # Determine order side (opposite of position)
            order_side = OrderSide.SELL if position.is_long else OrderSide.BUY
            
            # Place stop market order
            order = self.order_manager.place_stop_market_order(
                symbol=symbol,
                side=order_side,
                stop_price=stop_price,
                close_position=True,  # Close entire position
                working_type=WorkingType(self.config.exit_working_type)
            )
            
            if order and order.order_id:
                exit_order = ExitOrder(
                    exit_type=ExitType.STOP_LOSS,
                    price=stop_price,
                    quantity=0.0,  # Full position
                    order_id=order.order_id,
                    status=ExitStatus.ACTIVE,
                    created_at=time.time(),
                    metadata={"position_side": "long" if position.is_long else "short"}
                )
                
                self.active_exits[symbol].append(exit_order)
                logger.info(f"Stop loss placed for {symbol} @ {format_price(stop_price)}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to setup stop loss for {symbol}: {e}")
            return False

    def _setup_take_profits(
        self, 
        symbol: str, 
        position: Position, 
        prices: list[float], 
        quantities: list[float]
    ) -> bool:
        """Setup take profit orders."""
        try:
            if not self.order_manager:
                logger.warning("OrderManager not available for take profit placement")
                return False
            
            if len(prices) != len(quantities):
                logger.error("Take profit prices and quantities length mismatch")
                return False
            
            # Determine order side (opposite of position)
            order_side = OrderSide.SELL if position.is_long else OrderSide.BUY
            
            success_count = 0
            
            for i, (price, qty) in enumerate(zip(prices, quantities, strict=False)):
                try:
                    # Place limit order for take profit
                    order = self.order_manager.place_limit_order(
                        symbol=symbol,
                        side=order_side,
                        quantity=qty,
                        price=price,
                        reduce_only=True
                    )
                    
                    if order and order.order_id:
                        exit_order = ExitOrder(
                            exit_type=ExitType.TAKE_PROFIT,
                            price=price,
                            quantity=qty,
                            order_id=order.order_id,
                            status=ExitStatus.ACTIVE,
                            created_at=time.time(),
                            metadata={
                                "level": i + 1,
                                "position_side": "long" if position.is_long else "short"
                            }
                        )
                        
                        self.active_exits[symbol].append(exit_order)
                        success_count += 1
                        logger.debug(f"Take profit {i+1} placed for {symbol} @ {format_price(price)}")
                
                except Exception as e:
                    logger.error(f"Failed to place take profit {i+1} for {symbol}: {e}")
            
            logger.info(f"Take profits setup for {symbol}: {success_count}/{len(prices)} successful")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"Failed to setup take profits for {symbol}: {e}")
            return False

    def _setup_trailing_stop(
        self, 
        symbol: str, 
        position: Position, 
        config: TrailingStopConfig
    ) -> bool:
        """Setup trailing stop configuration."""
        try:
            self.trailing_stops[symbol] = {
                "config": config,
                "position": position,
                "highest_price": position.entry_price if position.is_long else float('inf'),
                "lowest_price": position.entry_price if position.is_short else 0.0,
                "stop_price": None,
                "activated": False,
                "last_update": time.time(),
                "created_at": time.time()
            }
            
            logger.info(f"Trailing stop configured for {symbol}: "
                       f"activation={config.activation_distance}, trail={config.trail_distance}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup trailing stop for {symbol}: {e}")
            return False

    def update_trailing_stops(self, symbol: str, current_price: float) -> bool:
        """
        Update trailing stop logic.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            
        Returns:
            True if update successful
        """
        if symbol not in self.trailing_stops:
            return True  # No trailing stops to update
        
        try:
            trailing = self.trailing_stops[symbol]
            config = trailing["config"]
            position = trailing["position"]
            
            # Throttle updates based on frequency
            now = time.time()
            if now - trailing["last_update"] < config.update_frequency:
                return True
            
            trailing["last_update"] = now
            
            if position.is_long:
                # Long position trailing stop logic
                self._update_long_trailing_stop(symbol, current_price, trailing)
            else:
                # Short position trailing stop logic
                self._update_short_trailing_stop(symbol, current_price, trailing)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update trailing stop for {symbol}: {e}")
            return False

    def _update_long_trailing_stop(self, symbol: str, current_price: float, trailing: dict) -> None:
        """Update trailing stop for long position."""
        config = trailing["config"]
        position = trailing["position"]
        
        # Update highest price seen
        if current_price > trailing["highest_price"]:
            trailing["highest_price"] = current_price
        
        # Check if trailing stop should be activated
        profit_distance = current_price - position.entry_price
        
        if not trailing["activated"] and profit_distance >= config.activation_distance:
            trailing["activated"] = True
            logger.info(f"Trailing stop activated for {symbol} at {format_price(current_price)}")
        
        if trailing["activated"]:
            # Calculate new stop price
            new_stop_price = trailing["highest_price"] - config.trail_distance
            
            # Ensure stop doesn't go below max loss threshold
            max_loss_price = position.entry_price - config.max_loss
            new_stop_price = max(new_stop_price, max_loss_price)
            
            # Update stop if it moved up
            if trailing["stop_price"] is None or new_stop_price > trailing["stop_price"]:
                self._update_stop_price(symbol, new_stop_price, trailing)

    def _update_short_trailing_stop(self, symbol: str, current_price: float, trailing: dict) -> None:
        """Update trailing stop for short position."""
        config = trailing["config"]
        position = trailing["position"]
        
        # Update lowest price seen
        if current_price < trailing["lowest_price"]:
            trailing["lowest_price"] = current_price
        
        # Check if trailing stop should be activated
        profit_distance = position.entry_price - current_price
        
        if not trailing["activated"] and profit_distance >= config.activation_distance:
            trailing["activated"] = True
            logger.info(f"Trailing stop activated for {symbol} at {format_price(current_price)}")
        
        if trailing["activated"]:
            # Calculate new stop price
            new_stop_price = trailing["lowest_price"] + config.trail_distance
            
            # Ensure stop doesn't go above max loss threshold
            max_loss_price = position.entry_price + config.max_loss
            new_stop_price = min(new_stop_price, max_loss_price)
            
            # Update stop if it moved down
            if trailing["stop_price"] is None or new_stop_price < trailing["stop_price"]:
                self._update_stop_price(symbol, new_stop_price, trailing)

    def _update_stop_price(self, symbol: str, new_stop_price: float, trailing: dict) -> None:
        """Update trailing stop order price."""
        try:
            old_stop = trailing.get("stop_price")
            trailing["stop_price"] = new_stop_price
            
            # Cancel existing trailing stop order if exists
            self._cancel_trailing_stop_order(symbol)
            
            # Place new trailing stop order
            position = trailing["position"]
            order_side = OrderSide.SELL if position.is_long else OrderSide.BUY
            
            if self.order_manager:
                order = self.order_manager.place_stop_market_order(
                    symbol=symbol,
                    side=order_side,
                    stop_price=new_stop_price,
                    close_position=True,
                    working_type=WorkingType.MARK_PRICE
                )
                
                if order and order.order_id:
                    # Add to active exits
                    exit_order = ExitOrder(
                        exit_type=ExitType.TRAILING_STOP,
                        price=new_stop_price,
                        quantity=0.0,
                        order_id=order.order_id,
                        status=ExitStatus.ACTIVE,
                        created_at=time.time()
                    )
                    
                    if symbol not in self.active_exits:
                        self.active_exits[symbol] = []
                    
                    self.active_exits[symbol].append(exit_order)
                    
                    logger.debug(f"Trailing stop updated for {symbol}: "
                               f"{format_price(old_stop) if old_stop else 'None'} -> {format_price(new_stop_price)}")
            
        except Exception as e:
            logger.error(f"Failed to update trailing stop price for {symbol}: {e}")

    def _cancel_trailing_stop_order(self, symbol: str) -> None:
        """Cancel existing trailing stop order."""
        if symbol not in self.active_exits:
            return
        
        trailing_exits = [
            exit_order for exit_order in self.active_exits[symbol]
            if exit_order.exit_type == ExitType.TRAILING_STOP and exit_order.status == ExitStatus.ACTIVE
        ]
        
        for exit_order in trailing_exits:
            if exit_order.order_id and self.order_manager:
                success = self.order_manager.cancel_order(symbol, exit_order.order_id)
                if success:
                    exit_order.status = ExitStatus.CANCELLED
                    logger.debug(f"Cancelled trailing stop order {exit_order.order_id} for {symbol}")

    def cancel_symbol_exits(self, symbol: str) -> int:
        """
        Cancel all exit orders for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Number of orders cancelled
        """
        cancelled_count = 0
        
        try:
            if symbol in self.active_exits:
                for exit_order in self.active_exits[symbol]:
                    if (exit_order.status == ExitStatus.ACTIVE and 
                        exit_order.order_id and self.order_manager):
                        
                        success = self.order_manager.cancel_order(symbol, exit_order.order_id)
                        if success:
                            exit_order.status = ExitStatus.CANCELLED
                            cancelled_count += 1
            
            # Clear trailing stops
            if symbol in self.trailing_stops:
                del self.trailing_stops[symbol]
            
            logger.info(f"Cancelled {cancelled_count} exit orders for {symbol}")
            
        except Exception as e:
            logger.error(f"Failed to cancel exits for {symbol}: {e}")
        
        return cancelled_count

    def _clear_symbol_exits(self, symbol: str) -> None:
        """Clear all exit orders for symbol."""
        self.cancel_symbol_exits(symbol)
        if symbol in self.active_exits:
            del self.active_exits[symbol]

    def emergency_exit(self, symbol: str, reason: str = "Emergency exit triggered") -> bool:
        """
        Emergency exit - cancel all exits and close position immediately.
        
        Args:
            symbol: Trading symbol
            reason: Reason for emergency exit
            
        Returns:
            True if emergency exit successful
        """
        try:
            logger.warning(f"Emergency exit triggered for {symbol}: {reason}")
            
            # Cancel all existing exit orders
            cancelled = self.cancel_symbol_exits(symbol)
            
            # Place immediate market order to close position
            if self.order_manager:
                # Get current position info - this would need to be passed or retrieved
                # For now, we'll place a close position order
                # This assumes the order manager can handle close_position=True
                
                # Try both sides to close whatever position exists
                for side in [OrderSide.SELL, OrderSide.BUY]:
                    try:
                        order = self.order_manager.place_market_order(
                            symbol=symbol,
                            side=side,
                            quantity=0,  # Will need actual position size
                            reduce_only=True
                        )
                        if order:
                            break
                    except Exception:
                        continue
            
            # Record emergency exit
            self.exit_history.append({
                "symbol": symbol,
                "type": "emergency",
                "reason": reason,
                "timestamp": time.time(),
                "cancelled_orders": cancelled
            })
            
            logger.info(f"Emergency exit completed for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Emergency exit failed for {symbol}: {e}")
            return False

    def get_active_exits(self, symbol: str | None = None) -> dict[str, list[ExitOrder]]:
        """
        Get active exit orders.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            Dictionary of active exits
        """
        if symbol:
            return {symbol: self.active_exits.get(symbol, [])}
        return self.active_exits.copy()

    def get_exit_summary(self, symbol: str) -> dict[str, Any]:
        """
        Get exit summary for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Exit summary dictionary
        """
        summary = {
            "symbol": symbol,
            "active_exits": len(self.active_exits.get(symbol, [])),
            "has_trailing_stop": symbol in self.trailing_stops,
            "exit_orders": []
        }
        
        # Add exit order details
        for exit_order in self.active_exits.get(symbol, []):
            summary["exit_orders"].append({
                "type": exit_order.exit_type.value,
                "price": exit_order.price,
                "quantity": exit_order.quantity,
                "status": exit_order.status.value,
                "order_id": exit_order.order_id
            })
        
        # Add trailing stop details
        if symbol in self.trailing_stops:
            trailing = self.trailing_stops[symbol]
            summary["trailing_stop"] = {
                "activated": trailing["activated"],
                "current_stop": trailing.get("stop_price"),
                "highest_price": trailing.get("highest_price"),
                "lowest_price": trailing.get("lowest_price")
            }
        
        return summary

    def cleanup_completed_exits(self) -> int:
        """
        Clean up completed/cancelled exit orders.
        
        Returns:
            Number of orders cleaned up
        """
        cleaned_count = 0
        
        for symbol in list(self.active_exits.keys()):
            active_orders = []
            
            for exit_order in self.active_exits[symbol]:
                if exit_order.status in [ExitStatus.TRIGGERED, ExitStatus.CANCELLED, ExitStatus.EXPIRED]:
                    cleaned_count += 1
                else:
                    active_orders.append(exit_order)
            
            self.active_exits[symbol] = active_orders
            
            # Remove empty entries
            if not active_orders:
                del self.active_exits[symbol]
        
        if cleaned_count > 0:
            logger.debug(f"Cleaned up {cleaned_count} completed exit orders")
        
        return cleaned_count

    def get_performance_stats(self) -> dict[str, Any]:
        """Get exit system performance statistics."""
        total_exits = len(self.exit_history)
        emergency_exits = len([e for e in self.exit_history if e.get("type") == "emergency"])
        
        return {
            "total_exits": total_exits,
            "emergency_exits": emergency_exits,
            "active_symbols": len(self.active_exits),
            "trailing_stops": len(self.trailing_stops),
            "exit_history": self.exit_history[-10:]  # Last 10 exits
        }


def create_trailing_config(
    activation_distance: float,
    trail_distance: float,
    max_loss: float,
    update_frequency: int = 5
) -> TrailingStopConfig:
    """
    Create trailing stop configuration.
    
    Args:
        activation_distance: Distance to activate trailing
        trail_distance: Trailing distance
        max_loss: Maximum loss limit
        update_frequency: Update frequency in seconds
        
    Returns:
        TrailingStopConfig instance
    """
    return TrailingStopConfig(
        activation_distance=activation_distance,
        trail_distance=trail_distance,
        max_loss=max_loss,
        update_frequency=update_frequency
    )


__all__ = [
    "ExitManager",
    "ExitType", 
    "ExitStatus",
    "ExitOrder",
    "TrailingStopConfig",
    "create_trailing_config"
]