# work/exchange/market_data.py
"""
Simple, dependency-light market data provider for Binance Futures.

Exposes:
  - class MarketDataProvider
    * async get_ticker(symbol) -> {"symbol": str, "price": float}
    * async get_candles(symbol, interval="1m", limit=200) -> list[dict]
      where each dict has numeric fields: open, high, low, close, volume,
      and integer timestamps: open_time, close_time (ms).

This provider works with or without authenticated client; when client is not
available, it uses public HTTP endpoints.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode

log = logging.getLogger(__name__)

BINANCE_FAPI_URL = "https://fapi.binance.com"

def _http_get_json(path: str, params: Dict[str, Any]) -> Any:
    qs = urlencode(params)
    url = f"{BINANCE_FAPI_URL}{path}?{qs}"
    req = Request(url, headers={"User-Agent": "mdp/1.0"})
    with urlopen(req, timeout=7) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            s = x.strip()
            if s == "":
                return None
            return float(s)
    except Exception:
        return None
    return None

@dataclass
class _ClientAdapter:
    """
    Optional adapter over exchange.client.BinanceClient.
    Only the methods we use are referenced; calls are guarded.
    """
    client: Any

    async def ticker_price(self, symbol: str) -> Optional[float]:
        try:
            fn = getattr(self.client, "ticker_price", None) or getattr(self.client, "get_symbol_price", None)
            if not fn:
                return None
            res = fn(symbol) if "symbol" in getattr(fn, "__code__", type("", (), {"co_varnames": ()})).co_varnames else fn()
            if asyncio.iscoroutine(res):
                res = await res
            price = _to_float(res if isinstance(res, (int, float, str)) else (res.get("price") if isinstance(res, dict) else None))
            return price
        except Exception as e:
            log.debug("client.ticker_price error: %s", e)
            return None

    async def klines(self, symbol: str, interval: str, limit: int) -> Optional[List[Any]]:
        try:
            fn = getattr(self.client, "get_klines", None) or getattr(self.client, "klines", None)
            if not fn:
                return None
            res = fn(symbol=symbol, interval=interval, limit=limit) if "symbol" in getattr(fn, "__code__", type("", (), {"co_varnames": ()})).co_varnames else fn(symbol, interval, limit)
            if asyncio.iscoroutine(res):
                res = await res
            return res
        except Exception as e:
            log.debug("client.klines error: %s", e)
            return None

class MarketDataProvider:
    def __init__(self, client: Optional[Any] = None):
        self.adapter = _ClientAdapter(client) if client is not None else None

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = str(symbol).upper()
        # Try client first
        if self.adapter:
            price = await self.adapter.ticker_price(sym)
            if price is not None:
                return {"symbol": sym, "price": float(price)}
        # Fallback: HTTP public endpoint
        try:
            data = await asyncio.to_thread(_http_get_json, "/fapi/v1/ticker/price", {"symbol": sym})
            price = _to_float(data.get("price"))
            return {"symbol": sym, "price": float(price) if price is not None else None}
        except Exception as e:
            log.debug("HTTP ticker error: %s", e)
            return {"symbol": sym, "price": None}

    @staticmethod
    def _normalize_klines(raw: List[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in raw or []:
            # Futures API returns a list format:
            # [ open_time, open, high, low, close, volume, close_time, ... ]
            try:
                open_time = int(row[0])
                close_time = int(row[6])
                o = _to_float(row[1]) or 0.0
                h = _to_float(row[2]) or o
                l = _to_float(row[3]) or o
                c = _to_float(row[4]) or o
                v = _to_float(row[5]) or 0.0
                out.append({
                    "open_time": open_time,
                    "close_time": close_time,
                    "open": float(o),
                    "high": float(h),
                    "low": float(l),
                    "close": float(c),
                    "volume": float(v),
                })
            except Exception:
                continue
        return out

    async def get_candles(self, symbol: str, interval: str = "1m", limit: int = 200) -> List[Dict[str, Any]]:
        sym = str(symbol).upper()
        # Try client first
        if self.adapter:
            raw = await self.adapter.klines(sym, interval, limit)
            if isinstance(raw, list) and raw:
                return self._normalize_klines(raw)
        # HTTP fallback
        try:
            raw = await asyncio.to_thread(_http_get_json, "/fapi/v1/klines", {"symbol": sym, "interval": interval, "limit": int(limit)})
            if isinstance(raw, list):
                return self._normalize_klines(raw)
        except Exception as e:
            log.debug("HTTP klines error: %s", e)
        return []
