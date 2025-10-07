# apply_patches.py
from __future__ import annotations
import os, re, io, sys, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent  # предполагаем запуск из crypto_trading_bot/work
OK = "\u2705"
WARN = "\u26A0\uFE0F"

# ---------- contents: new files ----------

EXITS_ADDON = r'''# exchange/exits_addon.py
from __future__ import annotations
import logging, time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

from core.config import get_config
from exchange.client import BinanceClient

log = logging.getLogger(__name__)

_FILTERS: Dict[str, Dict[str, float]] = {}
_EXIT_STATE: Dict[str, Dict[str, float]] = {}

def _dec_floor(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    q = Decimal(str(step))
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_DOWN))

def _side_to_str(side: str) -> str:
    s = str(side or "").upper()
    if s in ("BUY","SELL"): return s
    if s in ("LONG","+","B","OPEN_LONG"):  return "BUY"
    if s in ("SHORT","-","S","OPEN_SHORT"): return "SELL"
    return "BUY"

def _pos_to_close_side(pos_side: str) -> str:
    s = str(pos_side or "").upper()
    if s in ("LONG","BUY","B"): return "SELL"
    if s in ("SHORT","SELL","S"): return "BUY"
    return "SELL"

def _load_filters(client: BinanceClient, symbol: str) -> Dict[str, float]:
    sym = symbol.upper()
    if sym in _FILTERS:
        return _FILTERS[sym]
    info = client.get_exchange_info()
    tick = 0.01; step = 0.001; min_not = 5.0; mup = 1.15; mdn = 0.85
    for si in info.get("symbols", []):
        if str(si.get("symbol","")).upper() != sym:
            continue
        for f in si.get("filters", []):
            t = f.get("filterType")
            if t == "PRICE_FILTER":
                tick = float(f.get("tickSize", tick))
            elif t in ("LOT_SIZE","MARKET_LOT_SIZE"):
                step = float(f.get("stepSize", step))
            elif t in ("NOTIONAL","MIN_NOTIONAL"):
                mn = f.get("notional", f.get("minNotional", min_not))
                min_not = float(mn)
            elif t == "PERCENT_PRICE":
                mup = float(f.get("multiplierUp", mup))
                mdn = float(f.get("multiplierDown", mdn))
        break
    _FILTERS[sym] = {"tick": tick, "step": step, "min_not": min_not, "mup": mup, "mdn": mdn}
    return _FILTERS[sym]

def _mark_or_last(client: BinanceClient, symbol: str) -> float:
    mp = 0.0
    try:
        mp = float(client.get_mark_price(symbol))
    except Exception:
        mp = 0.0
    if mp and mp > 0:
        return mp
    try:
        t = client.get_ticker_price(symbol)
        return float(t.get("price","0") or 0.0)
    except Exception:
        return 0.0

def _clamp_percent_price(client: BinanceClient, symbol: str, price: float) -> float:
    f = _load_filters(client, symbol)
    ref = _mark_or_last(client, symbol) or float(price)
    lo  = ref * f["mdn"]
    hi  = ref * f["mup"]
    px  = min(max(float(price), lo), hi)
    return _dec_floor(px, f["tick"])

def _quant_price(client: BinanceClient, symbol: str, price: float) -> float:
    f = _load_filters(client, symbol)
    return _dec_floor(float(price), f["tick"])

def _quant_qty(client: BinanceClient, symbol: str, qty: float) -> float:
    f = _load_filters(client, symbol)
    return _dec_floor(float(qty), f["step"])

def _ensure_gate(symbol: str, key: str, cooldown_s: float) -> bool:
    st = _EXIT_STATE.setdefault(symbol, {})
    now = time.time()
    last = st.get(key, 0.0)
    if now - last < cooldown_s:
        return False
    st[key] = now
    return True

def ensure_sl_on_exchange(
    client: BinanceClient,
    symbol: str,
    position_side: str,
    stop_price: float,
    working_type: str = "MARK_PRICE",
    eps_ticks: int = 3,
) -> Dict[str, Any]:
    cfg = get_config()
    if not getattr(cfg, "place_exits_on_exchange", True):
        return {"status":"SKIP", "reason":"exits disabled"}
    if getattr(cfg, "dry_run", False):
        return {"status":"OK", "dry_run": True}
    cooldown = float(getattr(cfg, "exit_replace_cooldown", 20.0))
    if not _ensure_gate(symbol, "sl", cooldown):
        return {"status":"SKIP", "reason":"cooldown"}

    f = _load_filters(client, symbol)
    tick = f["tick"]
    mark = _mark_or_last(client, symbol)

    close_side = _pos_to_close_side(position_side)
    sp = float(stop_price or 0.0)
    if mark > 0:
        if close_side == "SELL":
            if sp >= mark:
                sp = max(mark - eps_ticks * tick, tick)
        else:
            if sp <= mark:
                sp = mark + eps_ticks * tick
    sp = _quant_price(client, symbol, sp)

    params = {
        "symbol": symbol.upper(),
        "side": close_side,
        "type": "STOP_MARKET",
        "stopPrice": str(sp),
        "workingType": str(working_type or "MARK_PRICE").upper(),
        "closePosition": "true",
        "newOrderRespType": "RESULT",
        "positionSide": "BOTH",
    }
    try:
        resp = client.place_order(**params)
        return {"status":"OK", "resp": resp, "stopPrice": sp}
    except Exception as e:
        log.error("SL place failed %s: %s", symbol, e)
        return {"status":"ERROR", "error": str(e)}

def ensure_tp_on_exchange(
    client: BinanceClient,
    symbol: str,
    position_side: str,
    qty: float,
    entry_price: float,
    tp_levels_pct: List[float],
    tp_shares: List[float],
    tif: str = "GTC",
    tp_prefix: str = "TP-",
) -> Dict[str, Any]:
    cfg = get_config()
    if not getattr(cfg, "place_exits_on_exchange", True):
        return {"status":"SKIP", "reason":"exits disabled"}
    if getattr(cfg, "dry_run", False):
        return {"status":"OK", "dry_run": True, "placed": 0}

    cooldown = float(getattr(cfg, "exit_replace_cooldown", 20.0))
    if not _ensure_gate(symbol, "tp", cooldown):
        return {"status":"SKIP", "reason":"cooldown"}

    f = _load_filters(client, symbol)
    min_not = f["min_not"]

    # cancel old TP with prefix
    try:
        for o in client.get_open_orders(symbol):
            coid = str(o.get("clientOrderId",""))
            if coid.startswith(tp_prefix):
                try:
                    client.cancel_order(symbol, orderId=o.get("orderId"))
                except Exception:
                    pass
    except Exception as e:
        log.warning("Get/Cancel open TP orders failed for %s: %s", symbol, e)

    placed = 0; skipped = 0; fails = 0
    closing_side = _pos_to_close_side(position_side)

    for i, (level, share) in enumerate(zip(tp_levels_pct, tp_shares), start=1):
        try:
            if float(share) <= 0.0:
                skipped += 1; continue
            part_qty = _quant_qty(client, symbol, float(qty) * float(share))
            if part_qty <= 0:
                skipped += 1; continue

            if str(position_side).upper() in ("LONG","BUY"):
                raw_px = float(entry_price) * (1.0 + float(level) / 100.0)
            else:
                raw_px = float(entry_price) * (1.0 - float(level) / 100.0)

            px = _clamp_percent_price(client, symbol, raw_px)
            if part_qty * px < min_not:
                skipped += 1; continue

            params = {
                "symbol": symbol.upper(),
                "side": closing_side,
                "type": "LIMIT",
                "timeInForce": str(tif or "GTC").upper(),
                "quantity": str(part_qty),
                "price": str(px),
                "reduceOnly": "true",
                "positionSide": "BOTH",
                "newClientOrderId": f"{tp_prefix}{i}-{int(time.time()*1000)}",
                "newOrderRespType": "RESULT",
            }
            client.place_order(**params)
            placed += 1

        except Exception as e:
            msg = str(e)
            if "Precision" in msg or "precision" in msg:
                try:
                    params["quantity"] = str(_quant_qty(client, symbol, float(params["quantity"])))
                    params["price"]    = str(_quant_price(client, symbol, float(params["price"])))
                    client.place_order(**params)
                    placed += 1
                    continue
                except Exception as e2:
                    log.warning("TP precision retry failed %s: %s", symbol, e2)
            elif "ReduceOnly" in msg or "-2022" in msg:
                try:
                    cur = 0.0
                    for p in client.get_positions():
                        if str(p.get("symbol","")).upper() == symbol.upper():
                            cur = abs(float(p.get("positionAmt","0") or 0.0)); break
                    part_qty2 = _quant_qty(client, symbol, min(part_qty, cur))
                    if part_qty2 > 0 and part_qty2 * float(params["price"]) >= min_not:
                        params["quantity"] = str(part_qty2)
                        client.place_order(**params)
                        placed += 1
                        continue
                except Exception:
                    pass
            log.warning("TP place failed %s L%d: %s", symbol, i, e)
            fails += 1

    return {"status":"OK" if placed>0 else "SKIP", "placed": placed, "skipped": skipped, "fails": fails}

def ensure_exits_on_exchange(
    client: BinanceClient,
    symbol: str,
    position_side: str,
    qty: float,
    entry_price: float,
    stop_price: float,
    tp_levels_pct: List[float],
    tp_shares: List[float],
    working_type: str = "MARK_PRICE",
) -> Dict[str, Any]:
    r1 = ensure_sl_on_exchange(client, symbol, position_side, stop_price, working_type=working_type)
    r2 = ensure_tp_on_exchange(client, symbol, position_side, qty, entry_price, tp_levels_pct, tp_shares)
    return {"sl": r1, "tp": r2}
'''

EXECUTION = r'''# runner/execution.py
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
'''

# ---------- helpers ----------

def write_file(path: Path, content: str, exist_ok: bool = True) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and exist_ok:
        # keep if identical
        old = path.read_text(encoding="utf-8", errors="ignore")
        if old == content:
            return False
    path.write_text(content, encoding="utf-8")
    return True

def backup(path: Path):
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

def ensure_imports(text: str) -> tuple[str, bool]:
    changed = False
    lines = text.splitlines()
    has_os = any(l.strip() == "import os" or l.strip().startswith("import os,") for l in lines)
    has_exec = any("from runner.execution import TradeExecutor" in l for l in lines)

    # find import block end
    insert_idx = 0
    for i, l in enumerate(lines[:50]):  # only top
        if l.strip().startswith(("import ", "from ")):
            insert_idx = i + 1
        elif l.strip() == "" or l.strip().startswith("#") or l.strip().startswith(('"""', "'''")):
            continue
        else:
            break

    new_lines = list(lines)
    ins = []
    if not has_os:
        ins.append("import os")
    if not has_exec:
        ins.append("from runner.execution import TradeExecutor")
    if ins:
        new_lines[insert_idx:insert_idx] = ins
        changed = True

    return "\n".join(new_lines) + ("\n" if not text.endswith("\n") else ""), changed

def fix_executor_init(text: str) -> tuple[str, bool]:
    changed = False
    new = text

    # 1) replace explicit client pass
    pat = re.compile(r"self\.trade_executor\s*=\s*TradeExecutor\s*\(\s*client\s*=\s*self\.client[^)]*\)", re.MULTILINE)
    if pat.search(new):
        new = pat.sub("self.trade_executor = TradeExecutor()", new)
        changed = True

    # 2) ensure self.trade_executor created in __init__ if missing
    if "self.trade_executor = TradeExecutor()" not in new:
        # try to insert after def __init__(
        m = re.search(r"def\s+__init__\s*\([^)]*\)\s*:\s*\n", new)
        if m:
            idx = m.end()
            # detect indent of next line
            after = new[idx:]
            nl = after.splitlines()
            indent = ""
            if nl:
                m2 = re.match(r"(\s*)", nl[0])
                indent = m2.group(1) if m2 else "    "
            insert = f"{indent}self.trade_executor = TradeExecutor()\n"
            new = new[:idx] + insert + new[idx:]
            changed = True

    return new, changed

def ensure_client_binding(text: str) -> tuple[str, bool]:
    changed = False
    lines = text.splitlines()
    new_lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        new_lines.append(l)
        m = re.search(r"self\.client\s*=\s*.+", l)
        if m:
            # look ahead for binding within next 5 lines
            ahead = "\n".join(lines[i+1:i+6])
            if "self.trade_executor.client = self.client" not in ahead:
                indent = re.match(r"(\s*)", l).group(1)
                new_lines.append(f'{indent}if getattr(self, "trade_executor", None): self.trade_executor.client = self.client')
                changed = True
        i += 1
    return "\n".join(new_lines) + ("\n" if not text.endswith("\n") else ""), changed

def patch_file(p: Path) -> bool:
    if not p.exists():
        print(f"{WARN} {p} not found, skip")
        return False
    backup(p)
    txt = p.read_text(encoding="utf-8", errors="ignore")

    any_change = False
    txt1, ch1 = ensure_imports(txt); any_change |= ch1
    txt2, ch2 = fix_executor_init(txt1); any_change |= ch2
    txt3, ch3 = ensure_client_binding(txt2); any_change |= ch3

    if any_change:
        p.write_text(txt3, encoding="utf-8")
        print(f"{OK} Patched {p.relative_to(BASE)}")
    else:
        print(f"{OK} {p.relative_to(BASE)} already patched")
    return any_change

def main():
    created = 0
    changed = 0

    # 1) new files
    ex_path = BASE / "exchange" / "exits_addon.py"
    if write_file(ex_path, EXITS_ADDON, exist_ok=True):
        created += 1
        print(f"{OK} Created/updated {ex_path.relative_to(BASE)}")
    else:
        print(f"{OK} {ex_path.relative_to(BASE)} up-to-date")

    ex2_path = BASE / "runner" / "execution.py"
    if write_file(ex2_path, EXECUTION, exist_ok=True):
        created += 1
        print(f"{OK} Created/updated {ex2_path.relative_to(BASE)}")
    else:
        print(f"{OK} {ex2_path.relative_to(BASE)} up-to-date")

    # 2) patch runners (paper + live if present)
    paper = BASE / "runner" / "paper.py"
    live  = BASE / "runner" / "live.py"

    if patch_file(paper):
        changed += 1
    if live.exists():
        if patch_file(live):
            changed += 1

    print("\nSummary:")
    print(f"  New/updated files: {created}")
    print(f"  Patched modules:   {changed}")
    print("\nDone.")

if __name__ == "__main__":
    main()
