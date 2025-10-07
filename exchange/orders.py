# exchange/orders.py
"""
Unified order management for AI Trading Bot (Binance UM Futures).

Key fixes in this revision:
- ACCEPT BOTH Enum AND str for side/type/tif/workingType (no `.value` misuse)
- PERCENT_PRICE clamp for LIMIT/TP using multiplierUp/Down
- Anti-2021 for STOP_MARKET closePosition (shift from mark by 2-3 ticks)
- Proper tick/step rounding and minNotional validation
"""

from __future__ import annotations
import time
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime

from core.config import get_config
from core.constants import OrderSide, OrderType, OrderStatus, TimeInForce, WorkingType
from core.types import Order, Position
from core.utils import round_price, round_qty, update_symbol_filters
from .client import BinanceClient

logger = logging.getLogger(__name__)

SideLike        = Union[OrderSide, str]
TypeLike        = Union[OrderType, str]
TimeInForceLike = Union[TimeInForce, str]
WorkingTypeLike = Union[WorkingType, str]


# --------------------- helpers: Enum/str normalization --------------------- #
def _as_side(side: SideLike) -> str:
    if isinstance(side, OrderSide):
        return side
    s = str(side).upper()
    if s in ("BUY", "SELL"):
        return s
    # tolerant aliases
    if s in ("LONG", "+", "B", "OPEN_LONG"):  return "BUY"
    if s in ("SHORT","-", "S", "OPEN_SHORT"): return "SELL"
    # fallback
    return "BUY"

def _as_type(tp: TypeLike) -> str:
    if isinstance(tp, OrderType):
        return tp.value
    s = str(tp).upper()
    if s in ("MARKET","LIMIT","STOP_MARKET","STOP","TAKE_PROFIT","TAKE_PROFIT_MARKET"):
        return s if s != "STOP" else "STOP_MARKET"
    return "MARKET"

def _as_tif(tif: TimeInForceLike) -> str:
    if isinstance(tif, TimeInForce):
        return tif.value
    s = str(tif).upper()
    return s if s in ("GTC","IOC","FOK","GTX") else "GTC"

def _as_working_type(wt: WorkingTypeLike) -> str:
    if isinstance(wt, WorkingType):
        return wt.value
    s = str(wt).upper()
    return s if s in ("MARK_PRICE","CONTRACT_PRICE") else "MARK_PRICE"


class OrderManager:
    """
    Unified order manager with safety checks and retry logic.

    Additions in this revision:
    - Accepts Enum or str for all categorical args
    - PERCENT_PRICE clamp for LIMITs
    - Anti-2021 immediate-trigger protection for SL
    """

    def __init__(self, client: BinanceClient):
        self.client = client
        self.config = get_config()

        # Cache for symbol filters (+ percent price multipliers)
        self._symbol_filters: Dict[str, Dict[str, float]] = {}

        # Exit order tracking
        self._exit_orders: Dict[str, Dict[str, Any]] = {}  # {symbol: {type: order_info}}
        self._last_exit_update: Dict[str, float] = {}

    # -------------------- Filters & shared utils -------------------- #
    def _get_symbol_filters(self, symbol: str) -> Dict[str, float]:
        """Load & cache filters: tick_size, lot_size, min_notional, mup, mdn."""
        sym = symbol.upper()
        if sym not in self._symbol_filters:
            try:
                info = self.client.get_exchange_info()
                flt = {"tick_size": 0.01, "lot_size": 0.001, "min_notional": 5.0, "mup": 5.0, "mdn": 5.0}
                for si in info.get("symbols", []):
                    if str(si.get("symbol","")).upper() != sym:
                        continue
                    for f in si.get("filters", []):
                        t = f.get("filterType")
                        if t == "PRICE_FILTER":
                            flt["tick_size"] = float(f.get("tickSize", flt["tick_size"]))
                        elif t in ("LOT_SIZE","MARKET_LOT_SIZE"):
                            flt["lot_size"] = float(f.get("stepSize", flt["lot_size"]))
                        elif t in ("MIN_NOTIONAL","NOTIONAL"):
                            mn = f.get("notional", f.get("minNotional", flt["min_notional"]))
                            flt["min_notional"] = float(mn)
                        elif t == "PERCENT_PRICE":
                            flt["mup"] = float(f.get("multiplierUp", flt["mup"]))
                            flt["mdn"] = float(f.get("multiplierDown", flt["mdn"]))
                    break
                self._symbol_filters[sym] = flt
                # keep project-level helpers in sync
                update_symbol_filters(sym, flt["tick_size"], flt["lot_size"], flt["min_notional"])
            except Exception as e:
                logger.warning(f"Failed to get filters for {sym}: {e}")
                self._symbol_filters[sym] = {"tick_size": 0.01, "lot_size": 0.001, "min_notional": 5.0, "mup": 5.0, "mdn": 5.0}
        return self._symbol_filters[sym]

    def _get_mark_or_last(self, symbol: str) -> float:
        """Best-effort current reference price (prefer mark)."""
        try:
            mp = float(self.client.get_mark_price(symbol))
        except Exception:
            mp = 0.0
        if mp and mp > 0:
            return mp
        try:
            t = self.client.get_ticker_price(symbol)
            return float(t.get("price", "0") or 0.0)
        except Exception:
            return 0.0

    def _clamp_percent_price(self, symbol: str, price: float) -> float:
        """Clamp price by PERCENT_PRICE around mark/last."""
        f = self._get_symbol_filters(symbol)
        ref = self._get_mark_or_last(symbol) or price
        lo = ref / (f["mdn"] if f["mdn"] > 0 else 5.0)
        hi = ref * (f["mup"] if f["mup"] > 0 else 5.0)
        px = min(max(float(price), lo), hi)
        return round_price(symbol, px, f["tick_size"])

    # -------------------- Validation -------------------- #
    def _validate_order_params(
        self,
        symbol: str,
        side: SideLike,
        quantity: float,
        price: Optional[float] = None,
        order_type: TypeLike = OrderType.MARKET
    ) -> Tuple[float, Optional[float]]:
        """Round qty/price, clamp PERCENT_PRICE, check minNotional."""
        f = self._get_symbol_filters(symbol)
        # qty
        qty = round_qty(symbol, float(quantity), f["lot_size"])
        if qty <= 0:
            raise ValueError(f"Quantity too small after rounding: {quantity} -> {qty}")
        # price
        adj_price: Optional[float] = None
        if price is not None:
            adj_price = self._clamp_percent_price(symbol, float(price))
            if adj_price <= 0:
                raise ValueError(f"Invalid price after rounding/clamp: {price} -> {adj_price}")
        # min notional
        chk_price = adj_price or self._get_mark_or_last(symbol)
        notional = qty * chk_price
        if notional < f["min_notional"]:
            raise ValueError(f"Order value {notional:.2f} below minimum {f['min_notional']:.2f}")
        return qty, adj_price

    # -------------------- Placement APIs -------------------- #
    def place_market_order(
        self,
        symbol: str,
        side: SideLike,
        quantity: float,
        reduce_only: bool = False,
        position_side: str = "BOTH"
    ) -> Optional[Order]:
        """Place MARKET order (Enum or str ‘side’ supported)."""
        try:
            qty, _ = self._validate_order_params(symbol, side, quantity, order_type="MARKET")
            params = {
                "symbol": symbol.upper(),
                "side": _as_side(side),
                "type": "MARKET",
                "quantity": str(qty),
                "newOrderRespType": "RESULT",
                "positionSide": position_side
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            resp = self.client.place_order(**params)
            return self._response_to_order(resp)
        except Exception as e:
            logger.error(f"Failed to place market order {symbol} {_as_side(side)} {quantity}: {e}")
            return None

    def place_limit_order(
        self,
        symbol: str,
        side: SideLike,
        quantity: float,
        price: float,
        time_in_force: TimeInForceLike = TimeInForce.GTC,
        reduce_only: bool = False,
        position_side: str = "BOTH"
    ) -> Optional[Order]:
        """Place LIMIT order with PERCENT_PRICE clamp and tick rounding."""
        try:
            qty, adj_price = self._validate_order_params(symbol, side, quantity, price, order_type="LIMIT")
            tif = _as_tif(time_in_force)
            params = {
                "symbol": symbol.upper(),
                "side": _as_side(side),
                "type": "LIMIT",
                "quantity": str(qty),
                "price": str(adj_price),
                "timeInForce": tif,
                "newOrderRespType": "RESULT",
                "positionSide": position_side
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            resp = self.client.place_order(**params)
            return self._response_to_order(resp)
        except Exception as e:
            logger.error(f"Failed to place limit order {symbol} {_as_side(side)} {quantity}@{price}: {e}")
            return None

    def place_stop_market_order(
        self,
        symbol: str,
        side: SideLike,
        quantity: float = None,
        stop_price: float = None,
        close_position: bool = False,
        working_type: WorkingTypeLike = WorkingType.MARK_PRICE,
        position_side: str = "BOTH"
    ) -> Optional[Order]:
        """
        Place STOP_MARKET for SL.
        Anti-2021: move stop 2-3 ticks away from mark to avoid immediate trigger.
        """
        try:
            if stop_price is None or stop_price <= 0:
                raise ValueError("stop_price must be positive")

            f = self._get_symbol_filters(symbol)
            mark = self._get_mark_or_last(symbol)
            eps = 2.0 * f["tick_size"]

            s = _as_side(side)
            sp = float(stop_price)

            # Anti -2021 immediate trigger fix
            if mark > 0:
                if s == "SELL":  # closing LONG -> stop below mark
                    if sp >= mark:
                        sp = max(mark - 3.0 * eps, f["tick_size"])
                else:            # BUY (closing SHORT) -> stop above mark
                    if sp <= mark:
                        sp = mark + 3.0 * eps

            sp = round_price(symbol, sp, f["tick_size"])
            wkt = _as_working_type(working_type)

            params = {
                "symbol": symbol.upper(),
                "side": s,
                "type": "STOP_MARKET",
                "stopPrice": str(sp),
                "workingType": wkt,
                "newOrderRespType": "RESULT",
                "positionSide": position_side
            }

            if close_position:
                params["closePosition"] = "true"
            else:
                if quantity is None:
                    raise ValueError("Quantity required when not using closePosition")
                q, _ = self._validate_order_params(symbol, side, float(quantity), order_type="STOP_MARKET")
                params["quantity"] = str(q)
                params["reduceOnly"] = "true"

            resp = self.client.place_order(**params)
            return self._response_to_order(resp)

        except Exception as e:
            logger.error(f"Failed to place stop order {symbol} {_as_side(side)} stop@{stop_price}: {e}")
            return None

    # -------------------- Open orders / Exits -------------------- #
    def cancel_order(self, symbol: str, order_id: Optional[str] = None, client_order_id: Optional[str] = None) -> bool:
        """Cancel by orderId or origClientOrderId."""
        if not order_id and not client_order_id:
            logger.error("Either order_id or client_order_id must be provided")
            return False
        try:
            kwargs = {"symbol": symbol.upper()}
            if order_id:
                kwargs["orderId"] = int(order_id)
            if client_order_id:
                kwargs["origClientOrderId"] = client_order_id
            self.client.cancel_order(**kwargs)
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {symbol} {order_id or client_order_id}: {e}")
            return False

    def cancel_all_open_orders(self, symbol: str) -> int:
        """Cancel all open orders for a symbol."""
        n = 0
        try:
            for o in self.client.get_open_orders(symbol):
                oid = o.get("orderId")
                if oid and self.cancel_order(symbol, str(oid)):
                    n += 1
        except Exception as e:
            logger.error(f"Failed to cancel all orders for {symbol}: {e}")
        return n

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        try:
            data = self.client.get_open_orders(symbol)
            return [self._response_to_order(d) for d in data]
        except Exception as e:
            logger.error(f"Failed to get open orders for {symbol or 'all'}: {e}")
            return []

    def setup_exit_orders(self, symbol: str, position: Position, stop_loss: float,
                          take_profits: List[float], tp_quantities: List[float]) -> None:
        """Place SL + multi-TP reduceOnly LIMITs with validation and anti-spam cleanup."""
        if position.is_flat:
            return
        side = "SELL" if position.is_long else "BUY"

        if stop_loss and stop_loss > 0:
            self._setup_stop_loss(symbol, side, stop_loss)

        if take_profits and tp_quantities:
            self._setup_take_profits(symbol, side, take_profits, tp_quantities)

    def _setup_stop_loss(self, symbol: str, side: SideLike, stop_price: float) -> None:
        try:
            self._cancel_existing_exit_order(symbol, "stop_loss")
            order = self.place_stop_market_order(
                symbol=symbol,
                side=side,
                stop_price=stop_price,
                close_position=True,
                working_type=_as_working_type(self.config.exit_working_type)
            )
            if order:
                self._exit_orders.setdefault(symbol, {})["stop_loss"] = {
                    "order_id": order.order_id,
                    "price": float(order.stop_price or stop_price),
                    "timestamp": time.time()
                }
                logger.info(f"Setup stop loss for {symbol} @ {order.stop_price or stop_price}")
        except Exception as e:
            logger.error(f"Failed to setup stop loss for {symbol}: {e}")

    def _setup_take_profits(self, symbol: str, side: SideLike,
                            prices: List[float], quantities: List[float]) -> None:
        try:
            self._cancel_existing_exit_order(symbol, "take_profits")
            f = self._get_symbol_filters(symbol)
            tp_orders = []
            s = _as_side(side)

            for i, (price, qty) in enumerate(zip(prices, quantities)):
                if qty is None or qty <= 0 or price is None or price <= 0:
                    continue
                safe_px = self._clamp_percent_price(symbol, float(price))
                adj_qty = round_qty(symbol, float(qty), f["lot_size"])
                if adj_qty * safe_px < f["min_notional"]:
                    continue  # skip too small parts

                order = self.place_limit_order(
                    symbol=symbol,
                    side=s,
                    quantity=adj_qty,
                    price=safe_px,
                    reduce_only=True
                )
                if order:
                    tp_orders.append({
                        "order_id": order.order_id,
                        "price": float(order.price or safe_px),
                        "quantity": float(order.quantity or adj_qty),
                        "level": i + 1
                    })

            if tp_orders:
                self._exit_orders.setdefault(symbol, {})["take_profits"] = tp_orders
                logger.info(f"Setup {len(tp_orders)} take profit orders for {symbol}")
        except Exception as e:
            logger.error(f"Failed to setup take profits for {symbol}: {e}")

    def _cancel_existing_exit_order(self, symbol: str, order_type: str) -> None:
        exit_info = self._exit_orders.get(symbol, {})
        if order_type == "stop_loss" and "stop_loss" in exit_info:
            oid = exit_info["stop_loss"]["order_id"]
            self.cancel_order(symbol, oid)
            del exit_info["stop_loss"]
        elif order_type == "take_profits" and "take_profits" in exit_info:
            for tp in exit_info["take_profits"]:
                self.cancel_order(symbol, tp["order_id"])
            del exit_info["take_profits"]

    def ensure_exit_orders(self, symbol: str, position: Position, stop_loss: float,
                           take_profits: List[float], tp_quantities: List[float]) -> None:
        """
        Ensure exits exist and are fresh. Uses cooldown to avoid spam.
        """
        if position.is_flat:
            self._cancel_existing_exit_order(symbol, "stop_loss")
            self._cancel_existing_exit_order(symbol, "take_profits")
            return

        now = time.time()
        last = self._last_exit_update.get(symbol, 0.0)
        cooldown = float(self.config.exit_replace_cooldown or 20)
        if now - last < cooldown:
            return

        if self._needs_update(symbol, stop_loss, take_profits, tp_quantities):
            self.setup_exit_orders(symbol, position, stop_loss, take_profits, tp_quantities)
            self._last_exit_update[symbol] = now

    def _needs_update(self, symbol: str, stop_loss: float,
                      take_profits: List[float], tp_quantities: List[float]) -> bool:
        exit_info = self._exit_orders.get(symbol, {})

        # SL
        if "stop_loss" in exit_info:
            cur = float(exit_info["stop_loss"]["price"])
            eps = float(self.config.exit_replace_eps or 0.0)
            if eps > 0:
                if abs(cur - float(stop_loss)) / max(1e-9, cur) > eps:
                    return True
        else:
            return True

        # TPs
        cur_tps = exit_info.get("take_profits", [])
        if len(cur_tps) != len(take_profits):
            return True
        eps = float(self.config.exit_replace_eps or 0.0)
        for cur_tp, new_p, new_q in zip(cur_tps, take_profits, tp_quantities):
            price_diff = abs(float(cur_tp["price"]) - float(new_p)) / max(1e-9, float(cur_tp["price"]))
            qty_diff = abs(float(cur_tp["quantity"]) - float(new_q)) / max(1e-9, float(cur_tp["quantity"]))
            if price_diff > eps or qty_diff > 0.01:
                return True
        return False

    # -------------------- Mapping -------------------- #
    def _response_to_order(self, r: Dict) -> Order:
        """Convert Binance response dict to project Order dataclass."""
        return Order(
            symbol=r.get("symbol", ""),
            side=OrderSide(r.get("side", "BUY")),
            type=OrderType(r.get("type", "MARKET")),
            quantity=float(r.get("origQty", r.get("quantity", "0") or 0)),
            price=float(r.get("price", "0") or 0) if r.get("price") else None,
            stop_price=float(r.get("stopPrice", "0") or 0) if r.get("stopPrice") else None,
            order_id=str(r.get("orderId", "")),
            client_order_id=r.get("clientOrderId"),
            status=OrderStatus(r.get("status", "NEW")) if r.get("status") else None,
            filled_qty=float(r.get("executedQty", "0") or 0),
            avg_price=float(r.get("avgPrice", "0") or 0) if r.get("avgPrice") else None,
            timestamp=datetime.now(),
            reduce_only=str(r.get("reduceOnly", "false")).lower() == "true",
            close_position=str(r.get("closePosition", "false")).lower() == "true",
        )
