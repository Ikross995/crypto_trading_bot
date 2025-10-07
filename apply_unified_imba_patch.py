# apply_unified_imba_patch.py
from __future__ import annotations
import re, shutil, sys, os
from pathlib import Path

OK   = "✅"
WARN = "⚠️"

BASE = Path(__file__).resolve().parent

def backup(p: Path, suf: str):
    if p.exists():
        p_bak = p.with_suffix(p.suffix + suf)
        shutil.copy2(p, p_bak)
        return p_bak.name
    return None

def write_file(p: Path, content: str, bak_suffix: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    bak = backup(p, bak_suffix)
    p.write_text(content.rstrip() + "\n", encoding="utf-8")
    if bak:
        print(f"{OK} Updated {p.relative_to(BASE)} (backup: {bak})")
    else:
        print(f"{OK} Created {p.relative_to(BASE)}")

# ---------------- sitecustomize.py (глобальные гварды + автозагрузка .env) ----------------
SITECONTENT = r"""# IMBA sitecustomize (unified guard + config loader)
import os, sys, builtins
try:
    print("✅ sitecustomize: global 'sig' guard & .env loader active")
except Exception:
    pass

# --- Global guards for legacy variables (idempotent) ---
for _name in ("sig", "signal", "trade_signal"):
    if not hasattr(builtins, _name):
        setattr(builtins, _name, None)

# --- Load .env from --config or IMBA_CONFIG_PATH (before CLI parses) ---
def _imba_grab_config(argv):
    path = os.environ.get("IMBA_CONFIG_PATH", "")
    if path:
        return path, argv
    if "--config" in argv:
        try:
            i = argv.index("--config")
            if i+1 < len(argv):
                path = argv[i+1]
                os.environ["IMBA_CONFIG_PATH"] = path
                # удалим пару, чтобы Click/Typer не ругался
                del argv[i:i+2]
                print(f"✅ sitecustomize: IMBA_CONFIG_PATH={path}")
        except Exception:
            pass
    return path, argv

def _imba_load_env(path):
    if not path:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=True)
        print(f"✅ sitecustomize: loaded .env from {path}")
    except Exception as e:
        print(f"⚠️ sitecustomize: dotenv load failed: {e}")

_cfg, _argv = _imba_grab_config(sys.argv)
_imba_load_env(_cfg)
sys.argv = _argv
"""

# ---------------- compat_complete.py / compat.py (validate_symbol stub, builtins guard, balance time-sync, signal normalizer) ----------------
COMPAT_BLOCKS = {
"BUILTINS_GUARD": r'''
# --- COMPAT: GLOBAL SIG GUARD (builtins, idempotent) ---
import builtins as _blt
for _nm in ("sig", "signal", "trade_signal"):
    if not hasattr(_blt, _nm):
        setattr(_blt, _nm, None)
''',

"VALIDATE_SYMBOL_STUB": r'''
# --- COMPAT: safe stub for core.utils.validate_symbol (idempotent) ---
try:
    import importlib, logging
    _lg = logging.getLogger("compat")
    try:
        _cu = importlib.import_module("core.utils")
    except Exception as _e:
        _lg.warning("compat: cannot import core.utils: %s", _e)
        _cu = None
    def _compat_validate_symbol(s):
        try: s = (s or "").strip().upper()
        except Exception: s = str(s).upper()
        return s
    if _cu is not None and not hasattr(_cu, "validate_symbol"):
        try:
            setattr(_cu, "validate_symbol", _compat_validate_symbol)
            _lg.info("compat: injected core.utils.validate_symbol stub")
        except Exception as _e:
            _lg.warning("compat: failed to inject validate_symbol: %s", _e)
except Exception as _e:
    import logging
    logging.getLogger("compat").warning("compat symbol stub failed: %s", _e)
''',

"BALANCE_TIMESYNC": r'''
# --- COMPAT: BinanceClient.get_account_balance with time-sync & DRY stub (idempotent) ---
try:
    import os, time, hmac, hashlib, logging, requests, urllib.parse
    from core.config import get_config
    from exchange.client import BinanceClient
    _clog = logging.getLogger("compat")

    def _compat__ensure_time_offset_ms(base_url: str):
        try:
            r = requests.get(base_url + "/fapi/v1/time", timeout=5)
            js = r.json()
            st = int(js.get("serverTime"))
            off = st - int(time.time()*1000)
            return off
        except Exception as e:
            _clog.warning("compat: time sync failed: %s", e)
            return 0

    def _compat_get_account_balance(self):
        cfg = get_config()
        # DRY/PAPER: не ходим в сеть
        if getattr(cfg, "dry_run", False) or str(getattr(cfg, "mode", "")).lower() == "paper":
            return float(getattr(cfg, "paper_balance_usdt", 1000.0))

        api_key = getattr(self, "api_key", None) or os.getenv("BINANCE_API_KEY", "")
        api_secret = getattr(self, "api_secret", None) or os.getenv("BINANCE_API_SECRET", "")
        if not api_key or not api_secret:
            return float(getattr(cfg, "paper_balance_usdt", 1000.0))

        base_url = "https://testnet.binancefuture.com" if getattr(cfg, "testnet", True) else "https://fapi.binance.com"
        recv_window = int(getattr(cfg, "recv_window_ms", 7000) or 7000)

        def _signed_params(params: dict) -> dict:
            # recvWindow ДО подписи (SAFE SIGNATURE PATCH)
            p = dict(params)
            p.setdefault("recvWindow", recv_window)
            q = urllib.parse.urlencode(p, doseq=True)
            sig = hmac.new(api_secret.encode("utf-8"), q.encode("utf-8"), hashlib.sha256).hexdigest()
            p["signature"] = sig
            return p

        if not hasattr(self, "_time_offset_ms"):
            self._time_offset_ms = 0

        for attempt in (0, 1):
            ts = int(time.time()*1000) + int(getattr(self, "_time_offset_ms", 0))
            params = {"timestamp": ts}
            headers = {"X-MBX-APIKEY": api_key}
            try:
                r = requests.get(base_url + "/fapi/v2/balance", params=_signed_params(params), headers=headers, timeout=12)
                try:
                    data = r.json()
                except Exception:
                    data = {"status_code": r.status_code, "text": r.text}

                if r.ok:
                    bal = 0.0
                    if isinstance(data, list):
                        for b in data:
                            if str(b.get("asset","")).upper() == "USDT":
                                try: bal = float(b.get("balance", 0.0))
                                except Exception: bal = 0.0
                                break
                    return float(bal)

                err_code = None
                if isinstance(data, dict):
                    err_code = data.get("code", None)
                if err_code in (-1021, -1022) and attempt == 0:
                    self._time_offset_ms = _compat__ensure_time_offset_ms(base_url)
                    _clog.info("compat: synced futures time, offset=%sms", self._time_offset_ms)
                    continue

                raise RuntimeError(f"REST GET /fapi/v2/balance failed [{r.status_code}]: {data}")

            except Exception as e:
                if attempt == 0:
                    self._time_offset_ms = _compat__ensure_time_offset_ms(base_url)
                    _clog.info("compat: retrying balance after sync, offset=%sms", self._time_offset_ms)
                    continue
                raise

    try:
        _orig_init = BinanceClient.__init__
        def _patched_init(self, *a, **k):
            _orig_init(self, *a, **k)
            if not hasattr(self, "_time_offset_ms"):
                self._time_offset_ms = 0
        BinanceClient.__init__ = _patched_init
    except Exception as _e:
        _clog.debug("compat: __init__ patch skipped: %s", _e)

    try:
        if getattr(BinanceClient.get_account_balance, "__name__", "") != "_compat_get_account_balance":
            BinanceClient.get_account_balance = _compat_get_account_balance
            _clog.info("compat: patched BinanceClient.get_account_balance (time-sync & DRY stub)")
    except Exception as _e:
        _clog.warning("compat: failed to patch get_account_balance: %s", _e)

except Exception as e:
    import logging
    logging.getLogger("compat").warning("compat patch (balance/timesync) failed: %s", e)
''',

"SIGNALS_NORMALIZER": r'''
# --- COMPAT: signal input normalizer + warning throttle (idempotent) ---
try:
    import logging, time, functools
    import strategy.signals as _sigmod
    _clog = logging.getLogger("compat")

    _warn_gate = {}
    def _throttle_warn(key: str, msg: str, every: float = 60.0):
        now = time.time()
        last = _warn_gate.get(key, 0.0)
        if now - last >= every:
            _warn_gate[key] = now
            try: _clog.warning(msg)
            except Exception: pass

    def _norm_md(md):
        def _one(x):
            try:
                if isinstance(x, (list, tuple)) and len(x) >= 5:
                    return float(x[4])
                if isinstance(x, dict):
                    for k in ("price","last","close","c"):
                        if k in x: return float(x[k])
                    if "k" in x and isinstance(x["k"], dict) and "c" in x["k"]:
                        return float(x["k"]["c"])
                if isinstance(x, (int,float)): return float(x)
                if isinstance(x, str): return float(x)
            except Exception:
                return None
            return None

        if isinstance(md, (list, tuple)):
            if md and isinstance(md[0], (list, tuple)) and len(md[0]) >= 5:
                return md
            vals = [v for v in (_one(x) for x in md) if v is not None]
            return vals[-1] if vals else md
        return _one(md) if md is not None else md

    wrapped = False
    if hasattr(_sigmod, "generate_signal") and callable(_sigmod.generate_signal):
        _orig = _sigmod.generate_signal
        @functools.wraps(_orig)
        def _compat_generate_signal(*a, **kw):
            if "market_data" in kw:
                kw = dict(kw); kw["market_data"] = _norm_md(kw["market_data"])
            try:
                return _orig(*a, **kw)
            except Exception as e:
                _throttle_warn("sig_call_fail", f"compat: generate_signal wrapper caught: {e}")
                raise
        _sigmod.generate_signal = _compat_generate_signal
        _clog.info("compat: wrapped strategy.signals.generate_signal (normalizer)")
        wrapped = True
    elif hasattr(_sigmod, "SignalGenerator") and hasattr(_sigmod.SignalGenerator, "generate"):
        _SG = _sigmod.SignalGenerator
        _orig = _SG.generate
        def _compat_generate(self, *a, **kw):
            if "market_data" in kw:
                kw = dict(kw); kw["market_data"] = _norm_md(kw["market_data"])
            try:
                return _orig(self, *a, **kw)
            except Exception as e:
                _throttle_warn("sig_method_fail", f"compat: SignalGenerator.generate wrapper caught: {e}")
                raise
        _SG.generate = _compat_generate
        _clog.info("compat: wrapped SignalGenerator.generate (normalizer)")
        wrapped = True

    if not wrapped:
        _clog.info("compat: signals normalizer not applied (no known entry point)")
except Exception as _e:
    import logging
    logging.getLogger("compat").warning("compat signals normalizer failed: %s", _e)
'''
}

def patch_compat():
    candidates = [BASE/"compat_complete.py", BASE/"compat.py"]
    any_found=False
    for p in candidates:
        if not p.exists():
            continue
        any_found=True
        src = p.read_text(encoding="utf-8", errors="ignore")
        changed = False
        out = src.rstrip() + "\n\n"
        for key, block in COMPAT_BLOCKS.items():
            if key not in ("SIGNALS_NORMALIZER", "BALANCE_TIMESYNC", "VALIDATE_SYMBOL_STUB", "BUILTINS_GUARD"):
                continue
            # idempotency by marker line
            marker = block.strip().splitlines()[0]
            if marker not in src:
                out += block.strip() + "\n\n"
                changed = True
        if changed:
            bak = backup(p, ".bak_unified")
            p.write_text(out, encoding="utf-8")
            print(f"{OK} Patched {p.relative_to(BASE)} (compat unified blocks added){' (backup: '+bak+')' if bak else ''}")
        else:
            print(f"{OK} {p.relative_to(BASE)} already has compat blocks")
    if not any_found:
        print(f"{WARN} compat_complete.py / compat.py not found — skipped")

# ---------------- cli_integrated.py shim (разрешаем --config после subcommand) ----------------
CLI_SHIM = r'''
# --- IMBA CLI shim: allow '--config PATH' after subcommand (idempotent) ---
try:
    import sys as _sys, os as _os
    if "--config" in _sys.argv:
        j = _sys.argv.index("--config")
        if j+1 < len(_sys.argv):
            _os.environ["IMBA_CONFIG_PATH"] = _sys.argv[j+1]
            # удалить пару, чтобы Click/Typer не ругался
            try:
                del _sys.argv[j:j+2]
            except Exception:
                pass
            print(f"✅ CLI shim: using config {_os.environ['IMBA_CONFIG_PATH']}")
except Exception as _e:
    pass
# --- /IMBA CLI shim ---
'''

def patch_cli():
    p = BASE/"cli_integrated.py"
    if not p.exists():
        print(f"{WARN} cli_integrated.py not found — skipped"); return
    src = p.read_text(encoding="utf-8", errors="ignore")
    if "IMBA CLI shim: allow '--config PATH'" in src:
        print(f"{OK} cli_integrated.py already has CLI shim"); return
    lines = src.splitlines(True)
    ins = 0
    # shebang/encoding/__future__
    if ins < len(lines) and lines[ins].startswith("#!"):
        ins += 1
    if ins < len(lines) and "coding" in lines[ins]:
        ins += 1
    while ins < len(lines) and lines[ins].strip().startswith("from __future__ import"):
        ins += 1
    # вставим shim
    lines[ins:ins] = [CLI_SHIM.strip() + "\n\n"]
    bak = backup(p, ".bak_cli")
    p.write_text("".join(lines), encoding="utf-8")
    print(f"{OK} Patched cli_integrated.py (CLI shim added){' (backup: '+bak+')' if bak else ''}")

# ---------------- runner safety (status log guard + exception traces) ----------------
RUNNER_HELPER = r'''
def _safe_pos_summary(pm):
    try:
        return pm.get_position_summary()
    except Exception:
        return {}
'''

def patch_runner(rel: str):
    p = BASE / rel
    if not p.exists():
        print(f"{WARN} {rel} not found — skipped"); return
    txt = p.read_text(encoding="utf-8", errors="ignore")
    changed=False
    if "_safe_pos_summary(" not in txt:
        # вставим helper сразу после импортов
        lines = txt.splitlines(True)
        ins = 0
        for i,l in enumerate(lines[:150]):
            if l.strip().startswith(("import ","from ")):
                ins = i+1
            elif l.strip()=="" or l.strip().startswith(("#",'"""',"'''")):
                continue
            else:
                break
        lines[ins:ins] = [RUNNER_HELPER.strip()+"\n\n"]
        txt = "".join(lines); changed=True
    # error -> exception (полный traceback)
    new_txt = re.sub(r"(\.logger|\slogger)\.error\(", r"\1.exception(", txt)
    if new_txt != txt:
        txt = new_txt; changed=True
    if changed:
        bak = backup(p, ".bak_runner")
        p.write_text(txt, encoding="utf-8")
        print(f"{OK} Patched {rel} (runner guards/trace){' (backup: '+bak+')' if bak else ''}")
    else:
        print(f"{OK} {rel} already safe")

def patch_runners():
    for rel in ("runner/paper.py", "runner/live.py"):
        patch_runner(rel)

# ---------------- core/utils.py (мягкая заглушка validate_symbol/normalize_symbol) ----------------
UTILS_STUB = r'''
# --- compat stub: validate_symbol / normalize_symbol (idempotent) ---
def validate_symbol(sym: str) -> str:
    try:
        s = str(sym).strip().upper()
    except Exception:
        return ""
    return s

def normalize_symbol(sym: str) -> str:
    return validate_symbol(sym)
'''

def patch_core_utils():
    p = BASE/"core"/"utils.py"
    if not p.exists():
        print(f"{WARN} core/utils.py not found — skipped"); return
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if "def validate_symbol" in txt:
        print(f"{OK} core/utils.py already has validate_symbol()"); return
    lines = txt.splitlines(True)
    ins = 0
    for i,l in enumerate(lines[:150]):
        if l.strip().startswith(("import ","from ")):
            ins = i+1
        elif l.strip()=="" or l.strip().startswith(("#","'''",'"""')):
            continue
        else:
            break
    lines[ins:ins] = [UTILS_STUB.strip()+"\n\n"]
    bak = backup(BASE/"core"/"utils.py", ".bak_utils")
    (BASE/"core"/"utils.py").write_text("".join(lines), encoding="utf-8")
    print(f"{OK} Patched core/utils.py (validate_symbol stub){' (backup: '+bak+')' if bak else ''}")

# ---------------- exchange/exits_addon.py (полный модуль SL/TP как в R8) ----------------
EXITS_ADDON = r'''# exchange/exits_addon.py
from __future__ import annotations
import logging, time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Tuple, Optional

from core.config import get_config
from exchange.client import BinanceClient

log = logging.getLogger(__name__)

_FILTERS: Dict[str, Dict[str, float]] = {}
_LAST_ENSURE: Dict[str, Dict[str, float]] = {}

def _flt(x, d=0.0) -> float:
    try: return float(x)
    except Exception: return d

def _floor_to_step(x: float, step: float) -> float:
    if step <= 0: return float(x)
    q = Decimal(str(step))
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_DOWN))

def _load_filters(client: BinanceClient, symbol: str) -> Dict[str, float]:
    sym = symbol.upper()
    if sym in _FILTERS: return _FILTERS[sym]
    info = client.get_exchange_info()
    tick = 0.01; step = 0.001; min_not = 5.0
    for si in info.get("symbols", []):
        if str(si.get("symbol","")).upper() != sym: continue
        for f in si.get("filters", []):
            t = f.get("filterType")
            if t == "PRICE_FILTER":
                tick = _flt(f.get("tickSize", tick), tick)
            elif t in ("LOT_SIZE","MARKET_LOT_SIZE"):
                step = _flt(f.get("stepSize", step), step)
            elif t in ("NOTIONAL","MIN_NOTIONAL"):
                v = f.get("notional", f.get("minNotional", min_not))
                min_not = _flt(v, min_not)
        break
    eps = get_config().exit_replace_eps if getattr(get_config(), "exit_replace_eps", 0.0) > 0 else (2.0 * tick)
    _FILTERS[sym] = {"tick": tick, "step": step, "minNotional": min_not, "eps": eps}
    return _FILTERS[sym]

def _q_price(client: BinanceClient, symbol: str, px: float) -> float:
    f = _load_filters(client, symbol)
    return _floor_to_step(float(px), f["tick"])

def _q_qty(client: BinanceClient, symbol: str, qty: float) -> float:
    f = _load_filters(client, symbol)
    return _floor_to_step(float(qty), f["step"])

def _ensure_gate(symbol: str, kind: str, cooldown: float) -> bool:
    st = _LAST_ENSURE.setdefault(symbol, {})
    now = time.time()
    key = f"{kind}_ts"
    last = st.get(key, 0.0)
    if now - last < max(2.0, cooldown):
        log.debug("Cooldown for %s/%s: %.1fs", symbol, kind, now - last)
        return False
    st[key] = now
    return True

def _pos_to_close_side(position_side: str) -> str:
    s = str(position_side or "").upper()
    if s in ("LONG","BUY","B"): return "SELL"
    if s in ("SHORT","SELL","S"): return "BUY"
    return "SELL"

def _get_last_or_mark(client: BinanceClient, symbol: str) -> float:
    try:
        mp = float(client.get_mark_price(symbol))
        if mp > 0: return mp
    except Exception: pass
    try:
        t = client.get_ticker_price(symbol); return float(t.get("price","0") or 0.0)
    except Exception: return 0.0

def ensure_sl_on_exchange(client: BinanceClient, symbol: str, position_side: str, stop_price: float,
                          working_type: str = "MARK_PRICE", eps_ticks: int = 3) -> Dict[str, Any]:
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
    mark = _get_last_or_mark(client, symbol)

    closing_side = _pos_to_close_side(position_side)
    sp = float(stop_price or 0.0)

    if mark > 0:
        if closing_side == "SELL" and sp >= mark:
            sp = max(mark - eps_ticks * tick, tick)
        if closing_side == "BUY" and sp <= mark:
            sp = mark + eps_ticks * tick

    sp = _q_price(client, symbol, sp)

    p = {
        "symbol": symbol.upper(),
        "side": closing_side,
        "type": "STOP_MARKET",
        "stopPrice": str(sp),
        "closePosition": "true",
        "workingType": str(working_type or "MARK_PRICE").upper(),
        "newOrderRespType": "RESULT",
        "positionSide": "BOTH",
    }
    try:
        resp = client.place_order(**p)
        _LAST_ENSURE.setdefault(symbol, {})["sl_px"] = sp
        log.info("%s SL ensured @ %s (STOP_MARKET closePosition)", symbol, sp)
        return {"status":"OK", "resp": resp, "stopPrice": sp}
    except Exception as e:
        log.error("%s ensure_sl_on_exchange fail: %s", symbol, e)
        return {"status":"ERROR", "error": str(e)}

def ensure_tp_on_exchange(client: BinanceClient, symbol: str, position_side: str, qty: float, entry_price: float,
                          tp_levels_pct: Optional[List[float]] = None, tp_shares: Optional[List[float]] = None,
                          tif: str = "GTC", tp_prefix: str = "TP-") -> Dict[str, Any]:
    cfg = get_config()
    if not getattr(cfg, "place_exits_on_exchange", True):
        return {"status":"SKIP", "reason":"exits disabled"}
    if getattr(cfg, "dry_run", False):
        return {"status":"OK", "dry_run": True, "placed": 0}

    cooldown = float(getattr(cfg, "exit_replace_cooldown", 20.0))
    if not _ensure_gate(symbol, "tp", cooldown):
        return {"status":"SKIP", "reason":"cooldown"}

    lv = tp_levels_pct or getattr(cfg, "tp_levels", [0.45, 1.0, 1.8])
    sh = tp_shares     or getattr(cfg, "tp_shares", [0.35, 0.35, 0.30])
    if isinstance(lv, str): lv = [float(x) for x in lv.split(",") if x.strip()]
    if isinstance(sh, str): sh = [float(x) for x in sh.split(",") if x.strip()]
    splits = list(zip(lv, sh))
    if not splits:
        return {"status":"SKIP", "reason":"no splits"}

    f = _load_filters(client, symbol)
    min_not = f["minNotional"]
    placed = 0; skipped = 0; fails = 0

    try:
        for o in client.get_open_orders(symbol):
            cid = str(o.get("clientOrderId",""))
            if cid.startswith(tp_prefix):
                try: client.cancel_order(symbol, orderId=o.get("orderId"))
                except Exception: pass
    except Exception as e:
        log.warning("%s get/cancel open TP fail: %s", symbol, e)

    closing_side = _pos_to_close_side(position_side)
    is_long = str(position_side).upper().startswith("L")

    for i, (level, share) in enumerate(splits, start=1):
        try:
            if float(share) <= 0.0:
                skipped += 1; continue
            part_qty = _q_qty(client, symbol, float(qty) * float(share))
            if part_qty <= 0:
                skipped += 1; continue

            target = float(entry_price) * (1.0 + float(level)/100.0 if is_long else 1.0 - float(level)/100.0)
            px = _q_price(client, symbol, target)

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
                    params["quantity"] = str(_q_qty(client, symbol, float(params["quantity"])))
                    params["price"]    = str(_q_price(client, symbol, float(params["price"])))
                    client.place_order(**params)
                    placed += 1; continue
                except Exception as e2:
                    log.warning("TP precision retry failed %s: %s", symbol, e2)
            if "ReduceOnly" in msg or "-2022" in msg:
                try:
                    cur = 0.0
                    for p in client.get_positions():
                        if str(p.get("symbol","")).upper() == symbol.upper():
                            cur = abs(_flt(p.get("positionAmt","0"))); break
                    part_qty2 = _q_qty(client, symbol, min(part_qty, cur))
                    if part_qty2 > 0 and part_qty2 * float(params["price"]) >= min_not:
                        params["quantity"] = str(part_qty2)
                        client.place_order(**params)
                        placed += 1; continue
                except Exception: pass
            log.warning("%s TP place fail L%d: %s", symbol, i, e)
            fails += 1

    if placed > 0:
        log.info("%s TP ensured (%d parts)", symbol, placed)
        return {"status":"OK", "placed": placed, "skipped": skipped, "fails": fails}
    return {"status":"SKIP", "reason":"no TP placed", "skipped": skipped, "fails": fails}

def ensure_exits_on_exchange(client: BinanceClient, symbol: str, position_side: str, qty: float, entry_price: float,
                             stop_price: float, working_type: str = "MARK_PRICE",
                             tp_levels_pct: Optional[List[float]] = None, tp_shares: Optional[List[float]] = None) -> Dict[str, Any]:
    r1 = ensure_sl_on_exchange(client, symbol, position_side, stop_price, working_type=working_type)
    r2 = ensure_tp_on_exchange(client, symbol, position_side, qty, entry_price, tp_levels_pct, tp_shares)
    return {"sl": r1, "tp": r2}
'''

def ensure_exits_addon():
    p = BASE/"exchange"/"exits_addon.py"
    if p.exists():
        # не перезаписываем без нужды: обновим, если нет ключевых сигнатур
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if "ensure_sl_on_exchange" in txt and "ensure_tp_on_exchange" in txt:
            print(f"{OK} exchange/exits_addon.py already present")
            return
    write_file(p, EXITS_ADDON, ".bak_exits")

def main():
    # 1) sitecustomize (гварды + .env loader)
    write_file(BASE/"sitecustomize.py", SITECONTENT, ".bak_site")

    # 2) compat (builtins guard + validate_symbol stub + balance time-sync + signals normalizer)
    patch_compat()

    # 3) CLI shim (--config после subcommand)
    patch_cli()

    # 4) runners (safe status log + tracebacks)
    patch_runners()

    # 5) core/utils validate_symbol stub (на случай прямых импортов)
    patch_core_utils()

    # 6) exits_addon (полный модуль SL/TP как в R8)
    ensure_exits_addon()

    print("\nDone.")

if __name__ == "__main__":
    main()
