# exchange/exits.py
"""
Adapter layer: ensure_* exits API that delegates to OrderManager logic.

This keeps a single source of truth for SL/TP behaviour in exchange.orders
and preserves compatibility for modules expecting ensure_* helpers.
"""
from __future__ import annotations

from typing import List

from core.config import get_config
from .client import BinanceClient
from .orders import OrderManager
from core.constants import OrderSide
from core.types import Position


def ensure_sl_on_exchange(symbol: str, pos_sign_or_side, stop_price: float) -> None:
    cfg = get_config()
    cli = BinanceClient(testnet=cfg.testnet)
    om = OrderManager(cli)
    # Normalize sign to OrderSide for closePosition SL
    sign = _pos_sign(pos_sign_or_side)
    side = OrderSide.SELL if sign > 0 else OrderSide.BUY
    # Use internal stop loss setup (closePosition)
    om._setup_stop_loss(symbol, side, float(stop_price))


def ensure_tp_on_exchange(symbol: str, pos_sign_or_side, qty: float, entry: float, tps: List[float], tp_shares: List[float]) -> None:
    cfg = get_config()
    cli = BinanceClient(testnet=cfg.testnet)
    om = OrderManager(cli)
    sign = _pos_sign(pos_sign_or_side)
    side = OrderSide.SELL if sign > 0 else OrderSide.BUY
    # Build pseudo-position to reuse OrderManager logic
    pos = Position(symbol=symbol, size=(abs(float(qty)) if sign > 0 else -abs(float(qty))), entry_price=float(entry))
    # Quantities per TP share
    shares = tp_shares or cfg.tp_shares()
    sm = sum(shares) if shares else 0.0
    if sm <= 0:
        shares = [1.0]
        sm = 1.0
    shares = [x / sm for x in shares]
    tp_qty = [abs(float(pos.size)) * s for s in shares[: len(tps)]]
    om._setup_take_profits(symbol, side, [float(x) for x in tps[: len(tp_qty)]], tp_qty)


def ensure_exits_on_exchange(symbol: str, pos_sign_or_side, qty: float, sl: float, tps: List[float], tp_shares: List[float]) -> None:
    cfg = get_config()
    cli = BinanceClient(testnet=cfg.testnet)
    om = OrderManager(cli)
    sign = _pos_sign(pos_sign_or_side)
    pos = Position(symbol=symbol, size=(abs(float(qty)) if sign > 0 else -abs(float(qty))), entry_price=0.0)
    om.setup_exit_orders(symbol, pos, float(sl), [float(x) for x in tps], tp_shares or cfg.tp_shares())


def _pos_sign(s) -> int:
    if isinstance(s, (int, float)):
        v = int(s)
        return 1 if v > 0 else (-1 if v < 0 else 0)
    s = str(s).lower()
    if s.startswith(("b", "l")):
        return 1
    if s.startswith("s"):
        return -1
    return 0
