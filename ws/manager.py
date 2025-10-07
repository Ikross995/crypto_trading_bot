# ws/manager.py
"""
WebSocket/ticker manager with graceful reconnect and HTTP fallback polling.

Exposes a global MARKET_STATE dict:
MARKET_STATE[symbol] = {
    "last_px": float,
    "obi": float,  # smoothed order-book imbalance
    "obi_raw": float,
    "ts": float,
}
"""
from __future__ import annotations

import threading, time, json, inspect
from typing import Optional, Dict, Any, List

from core.config import get_config
from exchange.binance_client import get_client, safe_call
from exchange.precision import adjust_price

MARKET_STATE: dict[str, dict] = {}

def _ms(symbol: str) -> dict:
    s = symbol.upper()
    row = MARKET_STATE.get(s)
    if not row:
        row = MARKET_STATE[s] = {"last_px": 0.0, "obi": 0.0, "obi_raw": 0.0, "ts": 0.0}
    return row

def set_last_px(symbol: str, px: float) -> None:
    st = _ms(symbol); st["last_px"] = float(px); st["ts"] = time.time()

def get_last_px(symbol: str) -> float:
    return float(_ms(symbol).get("last_px") or 0.0)

class WSManager:
    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.ws = None
        self.thread = None
        self._stop = threading.Event()
        self._using_ws = False
        self._last_try = 0.0

    def _on_message(self, _, msg):
        try:
            if isinstance(msg, (bytes, str)):
                try:
                    msg = json.loads(msg)
                except Exception:
                    return
            e = msg.get("e")
            if e in ("bookTicker","24hrTicker"):
                px = float(msg.get("c") or msg.get("C") or msg.get("lastPrice") or 0.0)
                if px > 0:
                    set_last_px(self.symbol, px)
            elif "k" in msg:  # kline
                k = msg["k"]
                if k.get("x"):
                    set_last_px(self.symbol, float(k.get("c") or 0.0))
        except Exception:
            pass

    def _depth_on_message(self, _, msg):
        try:
            bids = msg.get("b", []) or msg.get("bids", [])
            asks = msg.get("a", []) or msg.get("asks", [])
            bv = sum(float(b[0])*float(b[1]) for b in bids[:10]) if bids else 0.0
            av = sum(float(a[0])*float(a[1]) for a in asks[:10]) if asks else 0.0
            raw = 0.0
            if bv+av>0:
                raw = (bv-av)/(bv+av)
            cfg = get_config()
            alpha = float(cfg.OBI_ALPHA or 0.2)
            st = _ms(self.symbol)
            st["obi_raw"] = raw
            st["obi"] = (1.0-alpha)*float(st.get("obi", 0.0)) + alpha*raw
            st["ts"] = time.time()
        except Exception:
            pass

    def _start_ws(self) -> bool:
        cfg = get_config()
        try:
            from binance.websocket.spot.websocket_client import SpotWebsocketClient as _WSClient  # new sdk v3
        except Exception:
            try:
                from binance.streams import ThreadedWebsocketManager as _WSClient  # classic
            except Exception:
                _WSClient = None

        if _WSClient is None:
            return False

        ws_url = "wss://stream.binancefuture.com" if cfg.TESTNET else "wss://fstream.binance.com"
        try:
            params = {"on_message": self._on_message}
            try:
                sig = inspect.signature(_WSClient)
                names = set(sig.parameters.keys())
            except Exception:
                names = set()
            if "testnet" in names:
                params["testnet"] = bool(cfg.TESTNET)
            elif "stream_url" in names:
                params["stream_url"] = ws_url
            elif "ws_url" in names:
                params["ws_url"] = ws_url

            self.ws = _WSClient(**params)
            # subscribe
            try:
                if hasattr(self.ws, "book_ticker"):
                    self.ws.book_ticker(symbol=self.symbol)
                if hasattr(self.ws, "kline"):
                    self.ws.kline(symbol=self.symbol, interval=cfg.TIMEFRAME)
            except Exception:
                pass
            # depth lightweight for OBI
            try:
                if hasattr(self.ws, "diff_book_depth"):
                    self.ws.diff_book_depth(symbol=self.symbol, speed=cfg.WS_DEPTH_INTERVAL, level=cfg.WS_DEPTH_LEVEL, id=1, callback=self._depth_on_message)
            except Exception:
                pass

            try:
                if hasattr(self.ws, "start"):
                    self.ws.start()
            except Exception:
                pass
            self._using_ws = True
            return True
        except Exception:
            return False

    def start(self) -> None:
        if not get_config().ENABLE_WS:
            return
        if self._using_ws:
            return
        ok = self._start_ws()
        if not ok:
            # start polling thread
            self.thread = threading.Thread(target=self._poll_loop, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self.ws and hasattr(self.ws, "stop"):
                self.ws.stop()
        except Exception:
            pass

    def can_retry(self) -> bool:
        return (time.time() - self._last_try) > 10.0

    def reconnect(self) -> None:
        if not self.can_retry():
            return
        self._last_try = time.time()
        try:
            if self.ws and hasattr(self.ws, "stop"):
                try:
                    self.ws.stop()
                except Exception:
                    pass
            self.ws = None
            self._using_ws = False
            self._start_ws()
        except Exception:
            pass

    def _poll_loop(self):
        cfg = get_config()
        while not self._stop.is_set():
            try:
                cli = get_client()
                px = float(safe_call(cli.futures_mark_price, symbol=self.symbol).get("markPrice", 0.0))
                if px > 0: set_last_px(self.symbol, px)
            except Exception:
                pass
            self._stop.wait(max(1, int(getattr(cfg, "WS_POLL_SEC", 5))))
