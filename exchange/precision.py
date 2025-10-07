# exchange/precision.py
"""
Exchange precision & filters utilities.

- Fetch and cache symbol filters (tickSize/stepSize/minNotional/PERCENT_PRICE)
- Safe rounding of price/qty
- Clamp price into PERCENT_PRICE band around mark price
- Formatters fmt_price/fmt_qty
"""
from __future__ import annotations

import math
import time
from typing import Dict, Tuple

from .binance_client import get_client, safe_call
from core.config import get_config

_filters_cache: dict[str, dict] = {}
_filters_ts: dict[str, float] = {}

def _now() -> float:
    return time.time()

def _fetch_filters(symbol: str) -> dict:
    cfg = get_config()
    sym = symbol.upper()
    # cache 30 minutes
    if sym in _filters_cache and _now() - _filters_ts.get(sym, 0) < 1800:
        return _filters_cache[sym]
    out = {
        "tick": 0.01,
        "step": 0.001,
        "minNotional": float(cfg.MIN_TP_NOTIONAL_USDT),
        "pp": {"multiplierUp": 5.0, "multiplierDown": 5.0},
    }
    try:
        info = safe_call(get_client().futures_exchange_info)
        for s in info.get("symbols", []):
            if s.get("symbol") == sym:
                for f in s.get("filters", []):
                    t = f.get("filterType")
                    if t in ("LOT_SIZE","MARKET_LOT_SIZE"):
                        out["step"] = float(f.get("stepSize", out["step"]))
                    elif t == "PRICE_FILTER":
                        out["tick"] = float(f.get("tickSize", out["tick"]))
                    elif t == "PERCENT_PRICE":
                        out["pp"]["multiplierUp"] = float(f.get("multiplierUp", out["pp"]["multiplierUp"]))
                        out["pp"]["multiplierDown"] = float(f.get("multiplierDown", out["pp"]["multiplierDown"]))
                    elif t in ("NOTIONAL","MIN_NOTIONAL","MIN_NOTIONAL_V2"):
                        v = f.get("minNotional") or f.get("notional")
                        if v is not None:
                            out["minNotional"] = float(v)
                break
    except Exception:
        pass
    _filters_cache[sym] = out
    _filters_ts[sym] = _now()
    return out

def get_filters(symbol: str) -> Tuple[float,float,float,dict]:
    f = _fetch_filters(symbol)
    return f["step"], f["tick"], f["minNotional"], f["pp"]

def adjust_price(symbol: str, price: float) -> float:
    tick = _fetch_filters(symbol)["tick"]
    if tick <= 0: return float(price)
    return math.floor(float(price) / tick) * tick

def adjust_qty(symbol: str, qty: float) -> float:
    step = _fetch_filters(symbol)["step"]
    if step <= 0: return float(qty)
    q = math.floor(float(qty) / step) * step
    if q <= 0: q = step
    return q

def clamp_percent_price(symbol: str, price: float) -> float:
    """
    Clamp price into allowed PERCENT_PRICE band around current mark price to avoid -4131.
    """
    f = _fetch_filters(symbol)
    try:
        mp = float(safe_call(get_client().futures_mark_price, symbol=symbol.upper()).get("markPrice", 0.0))
        if mp <= 0: mp = float(price)
    except Exception:
        mp = float(price)
    lo = mp / (f["pp"]["multiplierDown"] if f["pp"]["multiplierDown"]>0 else 5.0)
    hi = mp * (f["pp"]["multiplierUp"] if f["pp"]["multiplierUp"]>0 else 5.0)
    return max(min(float(price), hi), lo)

def fmt_price(symbol: str, price: float) -> str:
    p = adjust_price(symbol, price)
    tick = _fetch_filters(symbol)["tick"]
    if tick <= 0: return str(p)
    dec = max(0, int(round(-math.log10(tick))))
    return f"{p:.{dec}f}"

def fmt_qty(symbol: str, qty: float) -> str:
    q = adjust_qty(symbol, qty)
    step = _fetch_filters(symbol)["step"]
    if step <= 0: return str(q)
    dec = max(0, int(round(-math.log10(step))))
    return f"{q:.{dec}f}"
