# exchange/binance_client.py
"""
Binance client factory + safe wrappers.

- get_client(): returns configured python-binance futures Client (singleton)
- safe_call(): retries on -1021, hard-fails on 401/403/-2015/-2014
- new_order_safe(): SDK first, REST fallback with SAFE SIGNATURE PATCH
- get_open_orders_safe(): resilient open orders retrieval
"""
from __future__ import annotations

import hmac, hashlib, time, os
from typing import Any, Dict, Optional
import requests

from core.config import get_config

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
except Exception:  # pragma: no cover
    Client = None
    class BinanceAPIException(Exception):
        def __init__(self, status_code=None, message="", code=None):
            super().__init__(message)
            self.status_code = status_code
            self.code = code

_client: Optional["Client"] = None

def _base_urls(testnet: bool) -> dict:
    return {
        "rest": "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com",
        "ws":   "wss://stream.binancefuture.com" if testnet else "wss://fstream.binance.com",
    }

def get_client() -> "Client":
    global _client
    cfg = get_config()
    if _client is not None:
        return _client
    if Client is None:
        raise RuntimeError("python-binance is required for live/paper modes")
    key, sec = cfg.BINANCE_API_KEY, cfg.BINANCE_API_SECRET
    testnet = bool(cfg.TESTNET)
    cli = Client(api_key=key, api_secret=sec, testnet=testnet)
    # Force futures endpoints
    try:
        cli.API_URL = _base_urls(testnet)["rest"]
    except Exception:
        pass
    _client = cli
    return _client

# ---------------- safe_call -----------------
def safe_call(fn, *args, **kwargs):
    """
    Unified wrapper around Binance client calls with:
    - hard fail on auth/permission errors (-2015/-2014 or HTTP 401/403)
    - soft retry on timestamp desync (-1021) after syncing time/sleeping
    - soft retry by recreating client once on transport errors
    """
    cfg = get_config()
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        status = getattr(e, "status_code", None) or getattr(e, "response", None)
        code = getattr(e, "code", None)
        msg = str(e)

        # Hard auth errors
        if status in (401,403) or code in (-2015, -2014):
            raise

        # Timestamp ahead: -1021
        if code == -1021 or "Timestamp for this request is outside of the recvWindow" in msg:
            try:
                # try futures time sync
                cli = get_client()
                try:
                    cli.futures_time()
                except Exception:
                    pass
                time.sleep(1.2)
                return fn(*args, **kwargs)
            except Exception as e2:
                # give up if persists
                raise e2

        # One reconnect attempt on transport issues
        if any(s in msg for s in ["_http", "send_request", "Connection", "Read timed out"]):
            try:
                # recreate client and retry once
                global _client
                _client = None
                cli = get_client()
                return fn(*args, **kwargs)
            except Exception as e3:
                raise e3
        # otherwise bubble up
        raise

# ------------- REST fallback w/ SAFE SIGNATURE PATCH ----------------
def _rest_headers() -> Dict[str,str]:
    cfg = get_config()
    return {
        "X-MBX-APIKEY": cfg.BINANCE_API_KEY or "",
        "Content-Type": "application/x-www-form-urlencoded"
    }

def _sign_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    SAFE SIGNATURE PATCH:
    - add recvWindow BEFORE signing
    - never mutate payload after signature
    """
    cfg = get_config()
    p = dict(payload)
    p.setdefault("timestamp", int(time.time()*1000))
    p.setdefault("recvWindow", int(cfg.RECV_WINDOW_MS))
    q = "&".join([f"{k}={p[k]}" for k in sorted(p.keys()) if p[k] is not None])
    sig = hmac.new((cfg.BINANCE_API_SECRET or "").encode("utf-8"), q.encode("utf-8"), hashlib.sha256).hexdigest()
    out = p.copy()
    out["signature"] = sig
    return out

def _rest_call(method: str, path: str, payload: Dict[str, Any]) -> Any:
    cfg = get_config()
    base = _base_urls(bool(cfg.TESTNET))["rest"]
    url = base + path
    signed = _sign_query(payload)
    if method == "GET":
        r = requests.get(url, params=signed, headers=_rest_headers(), timeout=10)
    elif method == "POST":
        r = requests.post(url, params=signed, headers=_rest_headers(), timeout=10)
    elif method == "DELETE":
        r = requests.delete(url, params=signed, headers=_rest_headers(), timeout=10)
    else:
        raise RuntimeError("Unsupported method")
    try:
        data = r.json()
    except Exception:
        data = {"status": r.status_code, "text": r.text}
    if not r.ok:
        raise RuntimeError(f"REST {method} {path} failed [{r.status_code}]: {data}")
    return data

# ------------- public safe helpers -------------------
def new_order_safe(**params):
    """
    Try via SDK first, then fallback to REST signing if SDK transport/signature glitches.
    """
    cli = get_client()
    try:
        return safe_call(cli.futures_create_order, **{k: v for k, v in params.items() if v is not None})
    except Exception as e:
        msg = str(e)
        if ("_http" in msg) or ("send_request" in msg) or ("Signature" in msg) or ("timestamp" in msg):
            return _rest_call("POST", "/fapi/v1/order", {k:v for k,v in params.items() if v is not None})
        raise

def get_open_orders_safe(symbol: Optional[str] = None):
    cli = get_client()
    try:
        if symbol:
            return safe_call(cli.futures_get_open_orders, symbol=symbol.upper())
        return safe_call(cli.futures_get_open_orders)
    except TypeError:
        # old signatures
        if symbol:
            return safe_call(cli.futures_get_open_orders, symbol.upper())
        return safe_call(cli.futures_get_open_orders)
    except Exception as e:
        # REST fallback
        payload = {}
        if symbol:
            payload["symbol"] = symbol.upper()
        return _rest_call("GET", "/fapi/v1/openOrders", payload)

def cancel_order_safe(symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None):
    cli = get_client()
    try:
        params = {"symbol": symbol.upper(), "orderId": orderId, "origClientOrderId": origClientOrderId}
        return safe_call(cli.futures_cancel_order, **{k:v for k,v in params.items() if v is not None})
    except Exception:
        return _rest_call("DELETE", "/fapi/v1/order", {"symbol": symbol.upper(), "orderId": orderId, "origClientOrderId": origClientOrderId})

def account_info_safe() -> Dict[str,Any]:
    cli = get_client()
    try:
        return safe_call(cli.futures_account)
    except Exception:
        return _rest_call("GET", "/fapi/v2/account", {})
