"""
Unified order management for AI Trading Bot.

Handles all order operations with safety checks, retries, and proper error handling.
Consolidates duplicate order logic from the original monolithic code.
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from core.config import get_config
from core.constants import OrderSide, OrderType, OrderStatus, TimeInForce, WorkingType
from core.types import Order, Position
from core.utils import round_price, round_qty, update_symbol_filters
from .client import BinanceClient

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Unified order manager with safety checks and retry logic.
    
    Features:
    - Price and quantity rounding
    - Order validation
    - Automatic retries
    - Position-aware order placement
    - Exit order management (SL/TP)
    """
    
    def __init__(self, client: BinanceClient):
        self.client = client
        self.config = get_config()
        
        # Cache for symbol filters
        self._symbol_filters: Dict[str, Dict[str, float]] = {}
        
        # Exit order tracking
        self._exit_orders: Dict[str, Dict[str, any]] = {}  # {symbol: {type: order_info}}
        self._last_exit_update: Dict[str, float] = {}
    
    def _get_symbol_filters(self, symbol: str) -> Dict[str, float]:
        """Get and cache symbol trading filters."""
        if symbol not in self._symbol_filters:
            try:
                exchange_info = self.client.get_exchange_info()
                
                for symbol_info in exchange_info.get("symbols", []):
                    if symbol_info["symbol"] == symbol:
                        filters = {"tick_size": 0.01, "lot_size": 0.001, "min_notional": 5.0}
                        
                        for f in symbol_info.get("filters", []):
                            if f["filterType"] == "PRICE_FILTER":
                                filters["tick_size"] = float(f["tickSize"])
                            elif f["filterType"] == "LOT_SIZE":
                                filters["lot_size"] = float(f["stepSize"])
                            elif f["filterType"] in ["MIN_NOTIONAL", "NOTIONAL"]:
                                filters["min_notional"] = float(f.get("notional", f.get("minNotional", 5.0)))
                        
                        self._symbol_filters[symbol] = filters
                        update_symbol_filters(symbol, filters["tick_size"], filters["lot_size"], filters["min_notional"])
                        break
                else:
                    # Symbol not found, use defaults
                    self._symbol_filters[symbol] = {"tick_size": 0.01, "lot_size": 0.001, "min_notional": 5.0}
                    
            except Exception as e:
                logger.warning(f"Failed to get filters for {symbol}: {e}")
                self._symbol_filters[symbol] = {"tick_size": 0.01, "lot_size": 0.001, "min_notional": 5.0}
        
        return self._symbol_filters[symbol]
    
    def _validate_order_params(self, symbol: str, side: OrderSide, quantity: float, 
                              price: Optional[float] = None, order_type: OrderType = OrderType.MARKET) -> Tuple[float, Optional[float]]:
        """Validate and adjust order parameters."""
        filters = self._get_symbol_filters(symbol)
        
        # Round quantity to lot size
        rounded_qty = round_qty(symbol, quantity, filters["lot_size"])
        if rounded_qty <= 0:
            raise ValueError(f"Quantity too small after rounding: {quantity} -> {rounded_qty}")
        
        # Round price if provided
        rounded_price = None
        if price is not None:
            rounded_price = round_price(symbol, price, filters["tick_size"])
            if rounded_price <= 0:
                raise ValueError(f"Invalid price after rounding: {price} -> {rounded_price}")
        
        # Check minimum notional
        check_price = rounded_price or self._get_current_price(symbol)
        notional = rounded_qty * check_price
        if notional < filters["min_notional"]:
            raise ValueError(f"Order value {notional:.2f} below minimum {filters['min_notional']:.2f}")
        
        return rounded_qty, rounded_price
    
    def _get_current_price(self, symbol: str) -> float:
        """Get current market price for symbol."""
        try:
            ticker = self.client.get_ticker_price(symbol)
            return float(ticker["price"])
        except Exception as e:
            logger.warning(f"Failed to get current price for {symbol}: {e}")
            return 0.0
    
    def place_market_order(self, symbol: str, side: OrderSide, quantity: float, 
                          reduce_only: bool = False, position_side: str = "BOTH") -> Optional[Order]:
        """
        Place a market order with validation and error handling.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Order quantity
            reduce_only: Whether this is a reduce-only order
            position_side: Position side (BOTH/LONG/SHORT)
        
        Returns:
            Order object if successful, None if failed
        """
        try:
            # Validate and adjust parameters
            adj_qty, _ = self._validate_order_params(symbol, side, quantity, order_type=OrderType.MARKET)
            
            # Build order parameters
            order_params = {
                "symbol": symbol,
                "side": side.value,
                "type": OrderType.MARKET.value,
                "quantity": str(adj_qty),
                "newOrderRespType": "RESULT",
                "positionSide": position_side
            }
            
            if reduce_only:
                order_params["reduceOnly"] = "true"
            
            # Place the order
            response = self.client.place_order(**order_params)
            
            # Convert response to Order object
            return self._response_to_order(response)
            
        except Exception as e:
            logger.error(f"Failed to place market order {symbol} {side.value} {quantity}: {e}")
            return None
    
    def place_limit_order(self, symbol: str, side: OrderSide, quantity: float, price: float,
                         time_in_force: TimeInForce = TimeInForce.GTC, reduce_only: bool = False,
                         position_side: str = "BOTH") -> Optional[Order]:
        """
        Place a limit order with validation and error handling.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Order quantity
            price: Limit price
            time_in_force: Order time in force
            reduce_only: Whether this is a reduce-only order
            position_side: Position side (BOTH/LONG/SHORT)
        
        Returns:
            Order object if successful, None if failed
        """
        try:
            # Validate and adjust parameters
            adj_qty, adj_price = self._validate_order_params(symbol, side, quantity, price, OrderType.LIMIT)
            
            # Build order parameters
            order_params = {
                "symbol": symbol,
                "side": side.value,
                "type": OrderType.LIMIT.value,
                "quantity": str(adj_qty),
                "price": str(adj_price),
                "timeInForce": time_in_force.value,
                "newOrderRespType": "RESULT",
                "positionSide": position_side
            }
            
            if reduce_only:
                order_params["reduceOnly"] = "true"
            
            # Place the order
            response = self.client.place_order(**order_params)
            
            # Convert response to Order object
            return self._response_to_order(response)
            
        except Exception as e:
            logger.error(f"Failed to place limit order {symbol} {side.value} {quantity}@{price}: {e}")
            return None
    
    def place_stop_market_order(self, symbol: str, side: OrderSide, quantity: float = None,
                               stop_price: float = None, close_position: bool = False,
                               working_type: WorkingType = WorkingType.MARK_PRICE,
                               position_side: str = "BOTH") -> Optional[Order]:
        """
        Place a stop market order (for stop losses).
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Order quantity (optional if close_position=True)
            stop_price: Stop trigger price
            close_position: Close entire position
            working_type: Working type (MARK_PRICE or CONTRACT_PRICE)
            position_side: Position side (BOTH/LONG/SHORT)
        
        Returns:
            Order object if successful, None if failed
        """
        try:
            # Build order parameters
            order_params = {
                "symbol": symbol,
                "side": side.value,
                "type": OrderType.STOP_MARKET.value,
                "stopPrice": str(round_price(symbol, stop_price)),
                "workingType": working_type.value,
                "newOrderRespType": "RESULT",
                "positionSide": position_side
            }
            
            if close_position:
                order_params["closePosition"] = "true"
            else:
                if quantity is None:
                    raise ValueError("Quantity required when not using closePosition")
                adj_qty, _ = self._validate_order_params(symbol, side, quantity, order_type=OrderType.STOP_MARKET)
                order_params["quantity"] = str(adj_qty)
                order_params["reduceOnly"] = "true"
            
            # Place the order
            response = self.client.place_order(**order_params)
            
            # Convert response to Order object  
            return self._response_to_order(response)
            
        except Exception as e:
            logger.error(f"Failed to place stop order {symbol} {side.value} stop@{stop_price}: {e}")
            return None
    
    def cancel_order(self, symbol: str, order_id: Optional[str] = None, 
                    client_order_id: Optional[str] = None) -> bool:
        """
        Cancel an order by ID or client order ID.
        
        Args:
            symbol: Trading symbol
            order_id: Exchange order ID
            client_order_id: Client order ID
        
        Returns:
            True if successful, False otherwise
        """
        if not order_id and not client_order_id:
            logger.error("Either order_id or client_order_id must be provided")
            return False
        
        try:
            kwargs = {"symbol": symbol}
            if order_id:
                kwargs["orderId"] = int(order_id)
            if client_order_id:
                kwargs["origClientOrderId"] = client_order_id
                
            self.client.cancel_order(**kwargs)
            return True
            
        except Exception as e:
            # Log warning but don't fail - order might already be filled/cancelled
            logger.warning(f"Failed to cancel order {symbol} {order_id or client_order_id}: {e}")
            return False
    
    def cancel_all_open_orders(self, symbol: str) -> int:
        """
        Cancel all open orders for a symbol.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Number of orders cancelled
        """
        cancelled_count = 0
        
        try:
            open_orders = self.client.get_open_orders(symbol)
            
            for order in open_orders:
                order_id = order.get("orderId")
                if order_id and self.cancel_order(symbol, str(order_id)):
                    cancelled_count += 1
                    
        except Exception as e:
            logger.error(f"Failed to cancel all orders for {symbol}: {e}")
        
        return cancelled_count
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        Get all open orders, optionally filtered by symbol.
        
        Args:
            symbol: Trading symbol (optional)
        
        Returns:
            List of Order objects
        """
        try:
            orders_data = self.client.get_open_orders(symbol)
            return [self._response_to_order(order_data) for order_data in orders_data]
        except Exception as e:
            logger.error(f"Failed to get open orders for {symbol or 'all'}: {e}")
            return []
    
    def setup_exit_orders(self, symbol: str, position: Position, stop_loss: float,
                         take_profits: List[float], tp_quantities: List[float]) -> None:
        """
        Setup stop loss and take profit orders for a position.
        
        Args:
            symbol: Trading symbol
            position: Current position
            stop_loss: Stop loss price
            take_profits: List of take profit prices
            tp_quantities: List of quantities for each TP level
        """
        if position.is_flat:
            return
        
        # Determine order side (opposite of position)
        order_side = OrderSide.SELL if position.is_long else OrderSide.BUY
        
        # Place stop loss order
        if stop_loss > 0:
            self._setup_stop_loss(symbol, order_side, stop_loss)
        
        # Place take profit orders
        if take_profits and tp_quantities:
            self._setup_take_profits(symbol, order_side, take_profits, tp_quantities)
    
    def _setup_stop_loss(self, symbol: str, side: OrderSide, stop_price: float) -> None:
        """Setup stop loss order."""
        try:
            # Cancel existing stop loss
            self._cancel_existing_exit_order(symbol, "stop_loss")
            
            # Place new stop loss (close position)
            order = self.place_stop_market_order(
                symbol=symbol,
                side=side,
                stop_price=stop_price,
                close_position=True,
                working_type=WorkingType(self.config.exit_working_type)
            )
            
            if order:
                self._exit_orders.setdefault(symbol, {})["stop_loss"] = {
                    "order_id": order.order_id,
                    "price": stop_price,
                    "timestamp": time.time()
                }
                logger.info(f"Setup stop loss for {symbol} @ {stop_price}")
                
        except Exception as e:
            logger.error(f"Failed to setup stop loss for {symbol}: {e}")
    
    def _setup_take_profits(self, symbol: str, side: OrderSide, prices: List[float], 
                           quantities: List[float]) -> None:
        """Setup take profit orders."""
        try:
            # Cancel existing take profits
            self._cancel_existing_exit_order(symbol, "take_profits")
            
            tp_orders = []
            
            for i, (price, qty) in enumerate(zip(prices, quantities)):
                order = self.place_limit_order(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    price=price,
                    reduce_only=True
                )
                
                if order:
                    tp_orders.append({
                        "order_id": order.order_id,
                        "price": price,
                        "quantity": qty,
                        "level": i + 1
                    })
            
            if tp_orders:
                self._exit_orders.setdefault(symbol, {})["take_profits"] = tp_orders
                logger.info(f"Setup {len(tp_orders)} take profit orders for {symbol}")
                
        except Exception as e:
            logger.error(f"Failed to setup take profits for {symbol}: {e}")
    
    def _cancel_existing_exit_order(self, symbol: str, order_type: str) -> None:
        """Cancel existing exit orders of specified type."""
        exit_info = self._exit_orders.get(symbol, {})
        
        if order_type == "stop_loss" and "stop_loss" in exit_info:
            order_id = exit_info["stop_loss"]["order_id"]
            self.cancel_order(symbol, order_id)
            del exit_info["stop_loss"]
        
        elif order_type == "take_profits" and "take_profits" in exit_info:
            for tp in exit_info["take_profits"]:
                order_id = tp["order_id"]
                self.cancel_order(symbol, order_id)
            del exit_info["take_profits"]
    
    def ensure_exit_orders(self, symbol: str, position: Position, stop_loss: float,
                          take_profits: List[float], tp_quantities: List[float]) -> None:
        """
        Ensure exit orders are properly placed and updated.
        Uses cooldown to prevent excessive API calls.
        
        Args:
            symbol: Trading symbol
            position: Current position
            stop_loss: Stop loss price
            take_profits: List of take profit prices  
            tp_quantities: List of quantities for each TP level
        """
        if position.is_flat:
            # Cancel all exit orders if position is closed
            self._cancel_existing_exit_order(symbol, "stop_loss")
            self._cancel_existing_exit_order(symbol, "take_profits")
            return
        
        # Check cooldown
        now = time.time()
        last_update = self._last_exit_update.get(symbol, 0)
        cooldown = self.config.exit_replace_cooldown
        
        if now - last_update < cooldown:
            return  # Skip update due to cooldown
        
        # Check if orders need updating
        needs_update = self._check_exit_orders_need_update(symbol, stop_loss, take_profits, tp_quantities)
        
        if needs_update:
            self.setup_exit_orders(symbol, position, stop_loss, take_profits, tp_quantities)
            self._last_exit_update[symbol] = now
    
    def _check_exit_orders_need_update(self, symbol: str, stop_loss: float,
                                     take_profits: List[float], tp_quantities: List[float]) -> bool:
        """Check if exit orders need to be updated."""
        exit_info = self._exit_orders.get(symbol, {})
        
        # Check stop loss
        if "stop_loss" in exit_info:
            current_sl_price = exit_info["stop_loss"]["price"]
            price_diff = abs(current_sl_price - stop_loss) / current_sl_price
            if price_diff > self.config.exit_replace_eps:
                return True
        else:
            return True  # No stop loss exists
        
        # Check take profits
        current_tps = exit_info.get("take_profits", [])
        if len(current_tps) != len(take_profits):
            return True
        
        for current_tp, new_price, new_qty in zip(current_tps, take_profits, tp_quantities):
            price_diff = abs(current_tp["price"] - new_price) / current_tp["price"]
            qty_diff = abs(current_tp["quantity"] - new_qty) / current_tp["quantity"]
            
            if price_diff > self.config.exit_replace_eps or qty_diff > 0.01:  # 1% quantity tolerance
                return True
        
        return False
    
    def _response_to_order(self, response: Dict) -> Order:
        """Convert Binance API response to Order object."""
        return Order(
            symbol=response.get("symbol", ""),
            side=OrderSide(response.get("side", "BUY")),
            type=OrderType(response.get("type", "MARKET")),
            quantity=float(response.get("origQty", response.get("quantity", "0"))),
            price=float(response.get("price", "0")) if response.get("price") else None,
            stop_price=float(response.get("stopPrice", "0")) if response.get("stopPrice") else None,
            order_id=str(response.get("orderId", "")),
            client_order_id=response.get("clientOrderId"),
            status=OrderStatus(response.get("status", "NEW")) if response.get("status") else None,
            filled_qty=float(response.get("executedQty", "0")),
            avg_price=float(response.get("avgPrice", "0")) if response.get("avgPrice") else None,
            timestamp=datetime.now(),
            reduce_only=str(response.get("reduceOnly", "false")).lower() == "true",
            close_position=str(response.get("closePosition", "false")).lower() == "true"
        )