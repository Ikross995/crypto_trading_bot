# runner/execution.py
from __future__ import annotations
import logging, time
from typing import Dict, Any, Optional, List

from core.config import get_config
from exchange.client import BinanceClient
from exchange.exits_addon import ensure_exits_on_exchange

log = logging.getLogger(__name__)

class TradeExecutor:
    def __init__(self, client: Optional[BinanceClient] = None):
        self.cfg = get_config()
        self.client = client or BinanceClient()

    def _position_side_from_signal(self, signal_type: str) -> str:
        s = str(signal_type or "").upper()
        return "LONG" if s == "BUY" else "SHORT"

    def _entry_side_from_signal(self, signal_type: str) -> str:
        s = str(signal_type or "").upper()
        return "BUY" if s == "BUY" else "SELL"

    def _current_price(self, symbol: str) -> float:
        mp = self.client.get_mark_price(symbol)
        try:
            mp = float(mp)
        except Exception:
            mp = 0.0
        if mp and mp > 0:
            return mp
        try:
            t = self.client.get_ticker_price(symbol)
            return float(t.get("price","0") or 0.0)
        except Exception:
            return 0.0

    def _calc_qty(self, symbol: str, entry_px: float, stop_px: float) -> float:
        try:
            bal = float(self.client.get_account_balance() or 0.0)
        except Exception:
            bal = 0.0
        risk_pct = float(getattr(self.cfg, "risk_per_trade_pct", 0.5))
        lev = int(getattr(self.cfg, "leverage", 5))
        if bal <= 0 or entry_px <= 0:
            return 0.0
        sl_dist = abs(entry_px - stop_px)
        if sl_dist <= 0:
            sl_dist = entry_px * float(getattr(self.cfg, "sl_fixed_pct", 0.3)) / 100.0
        if sl_dist <= 0:
            return 0.0
        usd = bal * (risk_pct / 100.0)
        qty = (usd / sl_dist) * lev
        return max(qty, 0.0)

    def handle_signal(
        self,
        symbol: str,
        signal: Dict[str, Any],
        tp_levels_pct: Optional[List[float]] = None,
        tp_shares: Optional[List[float]] = None,
        working_type: str = "MARK_PRICE",
    ) -> Dict[str, Any]:
        if not signal or signal.get("signal_type") not in ("BUY","SELL"):
            return {"status":"SKIP", "reason":"unsupported signal"}

        cfg = self.cfg
        tp_levels_pct = tp_levels_pct or getattr(cfg, "tp_levels", [0.45, 1.0, 1.8])
        tp_shares     = tp_shares or getattr(cfg, "tp_shares", [0.35, 0.35, 0.30])

        side_entry = self._entry_side_from_signal(signal["signal_type"])
        pos_side   = self._position_side_from_signal(signal["signal_type"])

        px = self._current_price(symbol)
        if px <= 0:
            return {"status":"SKIP", "reason":"no price"}

        sl_fpct = float(getattr(cfg, "sl_fixed_pct", 0.3))
        if pos_side == "LONG":
            sl_px = px * (1.0 - sl_fpct/100.0)
        else:
            sl_px = px * (1.0 + sl_fpct/100.0)

        qty = self._calc_qty(symbol, px, sl_px)
        if qty <= 0:
            return {"status":"SKIP", "reason":"qty=0"}

        params = {
            "symbol": symbol.upper(),
            "side": side_entry,
            "type": "MARKET",
            "quantity": str(qty),
            "newOrderRespType": "RESULT",
            "positionSide": "BOTH",
        }

        if getattr(cfg, "dry_run", False):
            log.info("DRY_RUN MARKET %s %s qty=%s", symbol, side_entry, qty)
            exec_px = px
        else:
            try:
                resp = self.client.place_order(**params)
                exec_px = float(resp.get("avgPrice") or resp.get("price") or px)
            except Exception as e:
                return {"status":"ERROR", "stage":"entry", "error": str(e)}

        res_exits = ensure_exits_on_exchange(
            self.client, symbol, pos_side, qty, exec_px, sl_px,
            tp_levels_pct=tp_levels_pct, tp_shares=tp_shares, working_type=working_type
        )
        return {"status":"OK", "entry_price": exec_px, "qty": qty, "exits": res_exits}
