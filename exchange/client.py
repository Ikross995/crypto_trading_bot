# exchange/client.py
"""
Integrated Binance futures client for the project's exchange layer.

Features ported from monolith:
- SAFE SIGNATURE PATCH: add recvWindow BEFORE signing, never mutate payload post-sign
- safe_call(): retries on -1021 (time desync), reconnects once on transport issues,
  hard-stops on 401/403/-2015/-2014
- REST fallback for order placement and open-orders retrieval when python-binance SDK glitches
- Testnet/Live switching via config, DRY_RUN mode
- Public methods preserved for compatibility with existing project:
    * get_exchange_info()
    * get_open_orders(symbol: str | None = None)
    * place_order(**order_params)
    * cancel_order(symbol: str, orderId: int | None = None, origClientOrderId: str | None = None)
    * get_account_balance()
    * get_positions()
    * change_leverage(symbol: str, leverage: int)
    * change_margin_type(symbol: str, marginType: str)
    * change_position_mode(dualSidePosition: bool)
    * get_mark_price(symbol: str)
    * get_historical_klines(symbol: str, interval: str, start_str: str, end_str: str | None, limit: int = 1500)

Plus project-level convenience/compat:
    * get_ticker_price(symbol) -> {"symbol","price"}
    * get_klines(symbol, interval="1m", limit=500)
    * get_current_price(symbol) -> float
    * get_balance() -> float
    * get_position_info()  # NEW: compat alias used by PositionManager
    * get_symbol_price(symbol) -> float  # NEW: compat alias used by MarketDataProvider
    * close()
    * MockBinanceClient / BinanceMarketDataClient / IntegratedBinanceClient
    * create_client(config=None)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, Optional, List

import requests

from core.config import get_config
from core.constants import TradingMode

logger = logging.getLogger(__name__)

# --- Optional SDK import (will work even if missing) ---
try:
    from binance.client import Client as _BinanceClient
    from binance.exceptions import BinanceAPIException
    _SDK = "binance"
except Exception:  # pragma: no cover
    _BinanceClient = None
    class BinanceAPIException(Exception):  # minimal shim
        def __init__(self, status_code=None, message="", code=None):
            super().__init__(message)
            self.status_code = status_code
            self.code = code
    _SDK = None


def _base_urls(testnet: bool) -> Dict[str, str]:
    return {
        "rest": "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com",
        "ws":   "wss://stream.binancefuture.com" if testnet else "wss://fstream.binance.com",
    }


class BinanceClient:
    """
    Wrapper over python-binance REST for UM Futures with resilient behaviour.

    Safe in LIVE and PAPER modes.
    When DRY_RUN=true or no API keys, place_order() simulates ack/fill for MARKET.
    """

    def __init__(self, *args, **kwargs) -> None:
        cfg = get_config()
        self.cfg = cfg
        self.session = requests.Session()

        # Allow explicit override via kwargs (compat with old calls)
        _kw_testnet = kwargs.get("testnet", None)
        self.testnet = bool(cfg.testnet if _kw_testnet is None else _kw_testnet)
        self._base = _base_urls(self.testnet)["rest"]

        # Accept multiple env var naming styles
        _kw_key = kwargs.get("api_key")
        _kw_sec = kwargs.get("api_secret")
        self.api_key = (_kw_key or cfg.binance_api_key or os.getenv("BINANCE_API_KEY") or "").strip()
        self.api_secret = (_kw_sec or cfg.binance_api_secret or os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_SECRET_KEY") or "").strip()

        # Underlying SDK client if available
        self.client: Optional[_BinanceClient] = None
        if _BinanceClient:
            try:
                self.client = _BinanceClient(api_key=self.api_key, api_secret=self.api_secret, testnet=self.testnet)
                # force UM base url
                try:
                    self.client.API_URL = self._base
                except Exception:
                    pass
            except Exception as e:  # pragma: no cover
                logger.warning("Failed to init python-binance client: %s", e)

        # Mode flags
        self.mode = getattr(cfg, "mode", TradingMode.PAPER)
        self.dry_run = bool(getattr(cfg, "dry_run", getattr(cfg, "DRY_RUN", False)))

        # One-shot time sync memo
        self._last_time_sync = 0.0

    # -------------------- SAFE CALL WRAPPER --------------------
    def safe_call(self, fn, *args, **kwargs):
        """
        - retry once on -1021 after time sync
        - recreate client on transport errors
        - hard-fail on 401/403/-2015/-2014
        """
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            code = getattr(e, "code", None)
            msg = str(e)

            # Auth errors: do not retry
            if status in (401, 403) or code in (-2015, -2014):
                raise

            # Timestamp / recvWindow issues
            if code == -1021 or "recvWindow" in msg or "outside of the recvWindow" in msg:
                self._sync_time()
                time.sleep(1.0)
                return fn(*args, **kwargs)

            # Transport glitches: recreate client once
            if any(s in msg for s in ("_http", "send_request", "Connection", "Read timed out")):
                try:
                    self._recreate_client()
                    return fn(*args, **kwargs)
                except Exception:
                    pass

            # bubble up
            raise

    def _recreate_client(self):
        if _BinanceClient is None:
            return
        self.client = _BinanceClient(api_key=self.api_key, api_secret=self.api_secret, testnet=self.testnet)
        try:
            self.client.API_URL = self._base
        except Exception:
            pass

    def _sync_time(self):
        now = time.time()
        if self.client is None or (now - self._last_time_sync) < 2.0:
            return
        try:
            _ = self.safe_call(self.client.futures_time)
            self._last_time_sync = now
        except Exception:
            pass

    # -------------------- SAFE SIGNING + REST FALLBACK --------------------
    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/x-www-form-urlencoded"}

    def _sign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        SAFE SIGNATURE PATCH:
        Add recvWindow BEFORE signing and NEVER mutate payload post-signature.
        """
        p = dict(payload or {})
        recv = int(getattr(self.cfg, "recv_window_ms", getattr(self.cfg, "RECV_WINDOW_MS", 7000)))
        p.setdefault("timestamp", int(time.time() * 1000))
        p.setdefault("recvWindow", recv)
        q = "&".join(f"{k}={p[k]}" for k in sorted(p.keys()) if p[k] is not None)
        sig = hmac.new(self.api_secret.encode("utf-8"), q.encode("utf-8"), hashlib.sha256).hexdigest()
        p["signature"] = sig
        return p

    def _rest(self, method: str, path: str, payload: Dict[str, Any]) -> Any:
        url = self._base + path
        signed = self._sign(payload)
        try:
            if method == "GET":
                r = self.session.get(url, params=signed, headers=self._headers(), timeout=10)
            elif method == "POST":
                r = self.session.post(url, params=signed, headers=self._headers(), timeout=10)
            elif method == "DELETE":
                r = self.session.delete(url, params=signed, headers=self._headers(), timeout=10)
            else:
                raise RuntimeError(f"Unsupported method {method}")
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else {"status": r.status_code, "text": r.text}
            if not r.ok:
                raise RuntimeError(f"REST {method} {path} failed [{r.status_code}]: {data}")
            return data
        except Exception as e:
            logger.error("REST call failed: %s %s payload=%s err=%s", method, path, payload, e)
            raise

    # -------------------- PUBLIC API --------------------
    def get_exchange_info(self) -> Dict[str, Any]:
        if self.client:
            try:
                return self.safe_call(self.client.futures_exchange_info)
            except Exception:
                pass
        # REST fallback
        return self._rest("GET", "/fapi/v1/exchangeInfo", {})

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.client:
            try:
                if symbol:
                    return self.safe_call(self.client.futures_get_open_orders, symbol=symbol.upper())
                return self.safe_call(self.client.futures_get_open_orders)
            except Exception as e:
                msg = str(e)
                if "_http" not in msg and "send_request" not in msg:
                    raise
        payload: Dict[str, Any] = {}
        if symbol:
            payload["symbol"] = symbol.upper()
        data = self._rest("GET", "/fapi/v1/openOrders", payload)
        return data if isinstance(data, list) else []

    def cancel_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        if self.dry_run:
            return {"symbol": symbol.upper(), "status": "CANCELED", "orderId": orderId or 0, "origClientOrderId": origClientOrderId or ""}
        if self.client:
            try:
                return self.safe_call(self.client.futures_cancel_order, symbol=symbol.upper(), orderId=orderId, origClientOrderId=origClientOrderId)
            except Exception as e:
                msg = str(e)
                if "_http" not in msg and "send_request" not in msg:
                    raise
        return self._rest("DELETE", "/fapi/v1/order", {"symbol": symbol.upper(), "orderId": orderId, "origClientOrderId": origClientOrderId})

    def place_order(self, **order_params) -> Dict[str, Any]:
        """
        General order placement entry point used by exchange.orders.
        Accepts usual futures params: symbol, side, type, quantity, price, timeInForce,
        reduceOnly, stopPrice, workingType, closePosition, positionSide.
        """
        params = {k: v for k, v in order_params.items() if v is not None}
        symbol = (params.get("symbol") or "").upper()
        if self.dry_run or not self.api_key or not self.api_secret:
            # simulate acknowledgment
            return {
                "symbol": symbol,
                "status": "FILLED" if params.get("type") == "MARKET" else "NEW",
                "type": params.get("type"),
                "side": params.get("side"),
                "price": params.get("price"),
                "stopPrice": params.get("stopPrice"),
                "origQty": params.get("quantity"),
                "executedQty": params.get("quantity") if params.get("type") == "MARKET" else "0",
                "reduceOnly": params.get("reduceOnly", False),
                "closePosition": params.get("closePosition", False),
            }

        # Try SDK first
        if self.client:
            try:
                return self.safe_call(self.client.futures_create_order, **params)
            except Exception as e:
                msg = str(e)
                # Fallback on transport/signature issues
                if "_http" in msg or "send_request" in msg or "Signature" in msg or "timestamp" in msg:
                    pass
                else:
                    raise
        # REST fallback
        return self._rest("POST", "/fapi/v1/order", params)

    def get_account_balance(self) -> float:
        if self.client:
            try:
                acc = self.safe_call(self.client.futures_account_balance)
                for it in acc:
                    if it.get("asset") in ("USDT","BUSD","USD"):
                        return float(it.get("balance", 0.0))
            except Exception:
                pass
        try:
            data = self._rest("GET", "/fapi/v2/balance", {})
            for it in data:
                if it.get("asset") in ("USDT","BUSD","USD"):
                    return float(it.get("balance", 0.0))
        except Exception:
            pass
        return 0.0

    # compat alias expected by runner.paper status logging
    def get_balance(self) -> float:
        return self.get_account_balance()

    def get_positions(self) -> List[Dict[str, Any]]:
        if self.client:
            try:
                return self.safe_call(self.client.futures_position_information)
            except Exception:
                pass
        try:
            return self._rest("GET", "/fapi/v2/positionRisk", {})
        except Exception:
            return []

    # --- NEW: compat alias, some code calls get_position_info() directly
    def get_position_info(self) -> List[Dict[str, Any]]:
        return self.get_positions()

    def change_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        if self.client:
            try:
                return self.safe_call(self.client.futures_change_leverage, symbol=symbol.upper(), leverage=int(leverage))
            except Exception:
                pass
        return self._rest("POST", "/fapi/v1/leverage", {"symbol": symbol.upper(), "leverage": int(leverage)})

    def change_margin_type(self, symbol: str, marginType: str) -> Dict[str, Any]:
        if self.client:
            try:
                return self.safe_call(self.client.futures_change_margin_type, symbol=symbol.upper(), marginType=str(marginType).upper())
            except Exception:
                pass
        return self._rest("POST", "/fapi/v1/marginType", {"symbol": symbol.upper(), "marginType": str(marginType).upper()})

    def change_position_mode(self, dualSidePosition: bool) -> Dict[str, Any]:
        if self.client:
            try:
                return self.safe_call(self.client.futures_change_position_mode, dualSidePosition=bool(dualSidePosition))
            except Exception:
                pass
        return self._rest("POST", "/fapi/v1/positionSide/dual", {"dualSidePosition": "true" if bool(dualSidePosition) else "false"})

    def get_mark_price(self, symbol: str) -> float:
        if self.client:
            try:
                data = self.safe_call(self.client.futures_mark_price, symbol=symbol.upper())
                return float(data.get("markPrice", 0.0))
            except Exception:
                pass
        try:
            data = self._rest("GET", "/fapi/v1/premiumIndex", {"symbol": symbol.upper()})
            return float(data.get("markPrice", 0.0))
        except Exception:
            return 0.0

    # ---------- Convenience & compat ----------
    def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        """Return {"symbol": "...", "price": float} with strict numeric price."""
        def _as_float(x, default=0.0) -> float:
            try:
                return float(x)
            except Exception:
                return default

        sym = str(symbol).upper()

        # SDK first
        if self.client:
            try:
                d = self.safe_call(self.client.futures_symbol_ticker, symbol=sym)
                return {"symbol": d.get("symbol", sym), "price": _as_float(d.get("price", 0.0))}
            except Exception:
                pass

        # Public REST (unsigned)
        try:
            d = self._rest("GET", "/fapi/v1/ticker/price", {"symbol": sym})
            return {"symbol": d.get("symbol", sym), "price": _as_float(d.get("price", 0.0))}
        except Exception:
            return {"symbol": sym, "price": 0.0}

    def get_symbol_price(self, symbol: str) -> float:
        """Compat alias some modules expect; returns last/ticker price as float."""
        try:
            t = self.get_ticker_price(symbol)
            return float(t.get("price", "0") or 0.0)
        except Exception:
            return 0.0

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 500) -> List[list]:
        """Return futures klines as list, compatible with python-binance format."""
        if self.client and hasattr(self.client, "futures_klines"):
            try:
                return self.safe_call(self.client.futures_klines, symbol=symbol.upper(), interval=interval, limit=int(limit))
            except Exception:
                pass
        # REST fallback
        try:
            # /fapi/v1/klines supports unsigned GET for public data
            url = self._base + "/fapi/v1/klines"
            r = requests.get(url, params={"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("get_klines REST failed for %s: %s", symbol, e)
            return []

    def get_current_price(self, symbol: str) -> float:
        """Prefer mark price; fallback to ticker last price."""
        mp = self.get_mark_price(symbol)
        if mp > 0:
            return mp
        t = self.get_ticker_price(symbol)
        try:
            return float(t.get("price", 0.0))
        except Exception:
            return 0.0

    def get_historical_klines(self, symbol: str, interval: str, start_str: str, end_str: Optional[str] = None, limit: int = 1500):
        """Delegate to SDK if available; otherwise use get_klines as limited replacement."""
        if self.client and hasattr(self.client, "get_historical_klines"):
            return self.safe_call(self.client.get_historical_klines, symbol, interval, start_str, end_str, limit)
        # Fallback: best-effort recent klines
        return self.get_klines(symbol, interval=interval, limit=limit)

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass
        try:
            if self.client and hasattr(self.client, "session"):
                self.client.session.close()
        except Exception:
            pass


# --- Lightweight compat shells expected by other parts of the project ---
class BinanceMarketDataClient:
    """Thin wrapper around BinanceClient exposing only market-data style helpers."""

    def __init__(self, config=None, underlying: Optional[BinanceClient] = None) -> None:
        self._cfg = config or get_config()
        self._api = underlying or BinanceClient(testnet=self._cfg.testnet)

    def initialize(self) -> None:
        # no-op, kept for API compatibility with older engines
        return None

    # Compat methods used by runner.paper/SignalGenerator
    def get_current_price(self, symbol: str) -> float:
        return self._api.get_current_price(symbol)

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 500) -> List[list]:
        return self._api.get_klines(symbol, interval=interval, limit=limit)


class MockBinanceClient(BinanceClient):
    """Mock client that behaves like dry-run regardless of keys; useful for paper tests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dry_run = True
        self.api_key = ""
        self.api_secret = ""


# Some code expects this alias
IntegratedBinanceClient = BinanceClient


def create_client(config=None) -> BinanceClient:
    """Factory used by legacy code paths."""
    if config is None:
        config = get_config()
    return BinanceClient(testnet=config.testnet)
