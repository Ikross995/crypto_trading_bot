# compat.py
# Совместимость и защитные обёртки для runner.paper / runner.live и клиентов биржи.

# --- GLOBAL SIG GUARD (builtins, idempotent) ---
import builtins as _blt

# --- COMPAT SIGNAL SIDE MAP PATCH ---
def _compat_map_side(side: str) -> str:
    s = str(side or "").strip().upper()
    if s in ("BUY", "LONG", "L"):   return "LONG"
    if s in ("SELL","SHORT","S"):   return "SHORT"
    return "NONE"
# (интегрировать этот маппер в месте, где формируется normalized signal)

if not hasattr(_blt, "sig"):
    _blt.sig = None
if not hasattr(_blt, "signal"):
    _blt.signal = None
if not hasattr(_blt, "trade_signal"):
    _blt.trade_signal = None

import importlib
import inspect
import time
import logging
import math
from functools import wraps

__COMPAT_APPLIED__ = False


# ====================== Утилиты ======================
class _PMPosition:
    __slots__ = ("symbol", "size", "entry_price", "side", "leverage",
                 "unrealized_pnl", "margin", "timestamp")

    def __init__(self, symbol, size=0.0, entry_price=0.0, side=None, leverage=None,
                 unrealized_pnl=0.0, margin=0.0, timestamp=None):
        self.symbol = symbol
        self.size = float(size)
        self.entry_price = float(entry_price)
        self.side = side
        self.leverage = leverage
        self.unrealized_pnl = float(unrealized_pnl)
        self.margin = float(margin)
        self.timestamp = time.time() if timestamp is None else timestamp


class _ExitDecision:
    __slots__ = ("exit", "should_exit", "reason", "exit_price")
    def __init__(self, exit=False, reason=None, exit_price=None):
        self.exit = bool(exit)
        self.should_exit = bool(exit)
        self.reason = reason
        self.exit_price = exit_price
    def __bool__(self):
        return self.exit


# --- Обёртка сигнала: await‑совместимый dict с обязательными полями
class _SignalEnvelope(dict):
    __slots__ = ()
    def __getattr__(self, name):
        if name in self: return self[name]
        raise AttributeError(name)
    def __await__(self):
        async def _coro(): return self
        return _coro().__await__()
    def __bool__(self): return True


class _AwaitableNone:
    __slots__ = ()
    def __await__(self):
        async def _coro(): return None
        return _coro().__await__()
    def __bool__(self): return False


def _pm_balance_from_client(client):
    for attr in ("get_account_balance", "get_balance", "balance"):
        if hasattr(client, attr):
            obj = getattr(client, attr)
            try:
                val = obj() if callable(obj) else obj
                if isinstance(val, (int, float)): return float(val)
                if isinstance(val, dict):
                    for k in ("available","free","balance"):
                        if k in val:
                            try: return float(val[k])
                            except Exception: pass
            except Exception:
                pass
    return 10000.0


# ====================== Нормализация конфига ======================
class _CfgWrapper:
    __slots__ = ("_base", "_extra")
    def __init__(self, base, extra: dict):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_extra", dict(extra))
    def __getattr__(self, name):
        ex = object.__getattribute__(self, "_extra")
        if name in ex: return ex[name]
        return getattr(object.__getattribute__(self, "_base"), name)
    def __setattr__(self, name, value):
        ex = object.__getattribute__(self, "_extra")
        if name in ex: ex[name] = value
        else: setattr(object.__getattribute__(self, "_base"), name, value)


def normalize_config(cfg):
    """
    Обязательные безопасные дефолты (доли/флаги):
      - max_daily_loss → 0.05
      - max_drawdown → 0.20
      - min_account_balance → 0.0
      - close_positions_on_exit → False
      - sl_fixed_pct → 0.003
      - trading_hours_enabled → False
      - trading_session_tz → "UTC"
      - strict_guards → False
      - funding_filter_threshold → 0.0
      - close_before_funding_min → 0
      - risk_per_trade → risk_per_trade_pct / 100.0  # OUR CRITICAL FIX
    """
    defaults = {
        "max_daily_loss": 0.05,
        "max_drawdown": 0.20,
        "min_account_balance": 0.0,
        "close_positions_on_exit": False,
        "sl_fixed_pct": 0.003,
        "trading_hours_enabled": False,
        "trading_session_tz": "UTC",
        "strict_guards": False,
        "funding_filter_threshold": 0.0,
        "close_before_funding_min": 0,
        "risk_per_trade": 0.005,  # Default fallback
    }
    
    # CRITICAL FIX: Add risk_per_trade property
    try:
        if not hasattr(cfg, 'risk_per_trade') and hasattr(cfg, 'risk_per_trade_pct'):
            defaults["risk_per_trade"] = cfg.risk_per_trade_pct / 100.0
        elif hasattr(cfg, 'risk_per_trade'):
            defaults["risk_per_trade"] = cfg.risk_per_trade
    except Exception:
        defaults["risk_per_trade"] = 0.005
    
    try:
        for k, v in defaults.items():
            if not hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg
    except Exception:
        extra = {k: getattr(cfg, k, v) for k, v in defaults.items()}
        return _CfgWrapper(cfg, extra)


# ====================== PositionManager патчи ======================
def _ensure_pm():
    try: pm_mod = importlib.import_module("exchange.positions")
    except Exception: return
    PM = getattr(pm_mod, "PositionManager", None)
    if PM is None: return

    if not hasattr(PM, "_pm_storage_ready"):
        def _pm_storage_ready(self):
            if not hasattr(self, "_pm_positions"):
                self._pm_positions = {}
        PM._pm_storage_ready = _pm_storage_ready

    if not hasattr(PM, "setup_symbol"):
        def setup_symbol(self, symbol: str):
            client = getattr(self, "client", None)
            lev = getattr(getattr(self, "config", None), "leverage", None)
            for fn in ("change_leverage","set_leverage"):
                if hasattr(client, fn) and lev:
                    try: getattr(client, fn)(symbol, lev)
                    except Exception: pass
            self._pm_storage_ready()
            if symbol not in self._pm_positions:
                self._pm_positions[symbol] = _PMPosition(symbol)
        PM.setup_symbol = setup_symbol

    if not hasattr(PM, "get_position"):
        def get_position(self, symbol: str, force_refresh: bool=False):
            self._pm_storage_ready()
            pos = self._pm_positions.get(symbol)
            if pos is None:
                pos = _PMPosition(symbol)
                self._pm_positions[symbol] = pos
            return pos
        PM.get_position = get_position

    # CRITICAL: Ensure initialize() method exists and is async
    if not hasattr(PM, "initialize") or not inspect.iscoroutinefunction(getattr(PM, "initialize")):
        async def initialize(self) -> None:
            """Initialize position manager - CRITICAL FIX FOR ORIGINAL ERROR"""
            self._pm_storage_ready()
            cfg = getattr(self, "config", None)
            raw = []
            if cfg is not None:
                if getattr(cfg, "symbol", None): raw.append(cfg.symbol)
                if getattr(cfg, "symbols", None):
                    raw.extend(cfg.symbols if isinstance(cfg.symbols, (list, tuple)) else [cfg.symbols])
            symbols, seen = [], set()
            for s in raw:
                if s and s not in seen: seen.add(s); symbols.append(s)
            for sym in symbols:
                try: self.setup_symbol(sym)
                except Exception:
                    self._pm_positions.setdefault(sym, _PMPosition(sym))
        PM.initialize = initialize

    # Add other missing methods from our fixes
    for method_name, method_impl in [
        ("get_all_positions", lambda self: [p for p in getattr(self, "_pm_positions", {}).values()]),
        ("get_account_balance", lambda self: float(_pm_balance_from_client(getattr(self, "client", None)))),
        ("clear_cache", lambda self: getattr(self, "_pm_positions", {}).clear()),
    ]:
        if not hasattr(PM, method_name):
            setattr(PM, method_name, method_impl)
def _ensure_client():
    """
    Делает клиентов совместимыми с вызовами вида:
        IntegratedBinanceClient(testnet=True, dry_run=False, ...)
    Подменяет класс на shim-подкласс с "гибким" __init__ и выставлением testnet base_url.
    Добавляет алиасы MarketData-клиентов и ставит прочие мелкие фиксы.
    """
    import importlib, inspect, logging

    log = logging.getLogger("compat")

    try:
        bc_mod = importlib.import_module("exchange.client")
    except Exception:
        return

    # --- Вспомогательная обёртка игнора "No need to change …"
    def _wrap_ignore_noop(fn):
        from functools import wraps
        @wraps(fn)
        def wrapper(self, *a, **k):
            try:
                return fn(self, *a, **k)
            except Exception as e:
                s = str(e)
                if ("-4046" in s or "-4059" in s or
                    "No need to change margin type" in s or
                    "No need to change position side" in s or
                    "No need to change leverage" in s or
                    "No need to change" in s):
                    return None
                raise
        return wrapper

    # --- Тестовые URL'ы (можете сменить на spot при необходимости)
    FUTURES_TESTNET_URL = getattr(bc_mod, "FUTURES_TESTNET_URL", "https://testnet.binancefuture.com")
    SPOT_TESTNET_URL    = getattr(bc_mod, "SPOT_TESTNET_URL",    "https://testnet.binance.vision")

    def _shim_class(C, prefer_spot: bool, name_hint: str):
        """Возвращает подкласс C с гибким __init__: съедает testnet/dry_run, ставит base_url при testnet."""
        if C is None or getattr(C, "__compat_shim__", False):
            return C

        # Разберём допустимые параметры оригинального __init__
        try:
            sig = inspect.signature(C.__init__)
            allowed = {p for p in sig.parameters if p != "self"}
        except Exception:
            # если сигнатуру не прочитали — пропускаем только самые типичные параметры
            allowed = {"api_key", "api_secret", "base_url", "timeout", "session"}

        prefer_spot = bool(prefer_spot)

        class _Shim(C):
            __compat_shim__ = True
            def __init__(self, *args, **kwargs):
                testnet = kwargs.pop("testnet", None)
                kwargs.pop("dry_run", None)  # игнорируем для клиента, движку не мешает

                # Если конструктор поддерживает base_url и его не передали — подставим при testnet=True
                if testnet and ("base_url" in allowed) and ("base_url" not in kwargs):
                    kwargs["base_url"] = SPOT_TESTNET_URL if prefer_spot else FUTURES_TESTNET_URL
                    log.info(f"compat: {name_hint or C.__name__} base_url set to TESTNET: {kwargs['base_url']}")

                # Пропустим дальше только допустимые ключи, чтобы не было TypeError
                if allowed:
                    kwargs = {k: v for k, v in kwargs.items() if k in allowed}

                super().__init__(*args, **kwargs)

        _Shim.__name__ = C.__name__
        _Shim.__qualname__ = C.__qualname__
        return _Shim

    # Если в модуле есть IntegratedBinanceClient — подменим на shim
    IC  = getattr(bc_mod, "IntegratedBinanceClient", None)
    BC  = getattr(bc_mod, "BinanceClient", None)
    MBC = getattr(bc_mod, "MockBinanceClient", None)

    if IC is not None:
        setattr(bc_mod, "IntegratedBinanceClient", _shim_class(IC, prefer_spot=False, name_hint="IntegratedBinanceClient"))
    if BC is not None:
        setattr(bc_mod, "BinanceClient",          _shim_class(BC, prefer_spot=False, name_hint="BinanceClient"))
    if MBC is not None:
        setattr(bc_mod, "MockBinanceClient",      _shim_class(MBC, prefer_spot=False, name_hint="MockBinanceClient"))

    # Алиасы для клиентов рыночных данных (на случай старых импортов)
    if not hasattr(bc_mod, "BinanceMarketDataClient") and hasattr(bc_mod, "BinanceClient"):
        setattr(bc_mod, "BinanceMarketDataClient", getattr(bc_mod, "BinanceClient"))
    if not hasattr(bc_mod, "MockBinanceMarketDataClient") and hasattr(bc_mod, "MockBinanceClient"):
        setattr(bc_mod, "MockBinanceMarketDataClient", getattr(bc_mod, "MockBinanceClient"))
    if not hasattr(bc_mod, "MarketDataClient") and hasattr(bc_mod, "BinanceMarketDataClient"):
        setattr(bc_mod, "MarketDataClient", getattr(bc_mod, "BinanceMarketDataClient"))

    # Поверх — «шумные» вызовы и безопасное закрытие
    for cls_name in ("IntegratedBinanceClient","BinanceClient","MockBinanceClient",
                     "BinanceMarketDataClient","MockBinanceMarketDataClient"):
        C = getattr(bc_mod, cls_name, None)
        if C is None:
            continue

        # Игнорируем «No need to change …»
        for name in ("change_margin_type","set_margin_type",
                     "change_position_mode","set_position_mode",
                     "change_leverage","set_leverage"):
            if hasattr(C, name):
                fn = getattr(C, name)
                if not getattr(fn, "__compat_wrapped__", False):
                    wrapped = _wrap_ignore_noop(fn)
                    setattr(wrapped, "__compat_wrapped__", True)
                    setattr(C, name, wrapped)

        # Безопасное закрытие: await client.close()
        async def _async_close(self):  # noqa
            return None
        if not hasattr(C, "close") or not inspect.iscoroutinefunction(getattr(C, "close")):
            C.close = _async_close
        if not hasattr(C, "aclose"):
            C.aclose = _async_close


# (continue with rest of compat.py implementation...)

# ====================== apply() ======================
def apply():
    global __COMPAT_APPLIED__
    if __COMPAT_APPLIED__: return
    __COMPAT_APPLIED__ = True
    _ensure_pm()
    # _ensure_exits()
    # _ensure_signal_wrappers() 
    # _ensure_om()
    # _ensure_client()
    # _ensure_metrics()
    # _patch_runners()
    # _install_noise_filter()

# === COMPAT PATCH: BinanceClient.get_account_balance with time-sync & DRY_RUN stub (idempotent) ===
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
            # нет ключей — безопасный дефолт
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

        # первичный timestamp c учётом (возможного) оффсета
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

                # разбор ошибки (например, -1021/-1022)
                err_code = None
                if isinstance(data, dict):
                    err_code = data.get("code", None)
                if err_code in (-1021, -1022) and attempt == 0:
                    # Синхронизация времени + ретрай
                    self._time_offset_ms = _compat__ensure_time_offset_ms(base_url)
                    _clog.info("compat: synced futures time, offset=%sms", self._time_offset_ms)
                    continue

                raise RuntimeError(f"REST GET /fapi/v2/balance failed [{r.status_code}]: {data}")

            except Exception as e:
                if attempt == 0:
                    # ещё одна попытка после sync (вдруг это сетевой глич)
                    self._time_offset_ms = _compat__ensure_time_offset_ms(base_url)
                    _clog.info("compat: retrying balance after sync, offset=%sms", self._time_offset_ms)
                    continue
                raise

    # аккуратно дополним __init__, чтобы был _time_offset_ms
    try:
        _orig_init = BinanceClient.__init__
        # -- removed recursive _patched_init --
    except Exception as _e:
        _clog.debug("compat: __init__ patch skipped: %s", _e)

    # подключаем новую реализацию баланса
    try:
        BinanceClient.get_account_balance = _compat_get_account_balance
        _clog.info("compat: patched BinanceClient.get_account_balance (time-sync & DRY stub)")
    except Exception as _e:
        _clog.warning("compat: failed to patch get_account_balance: %s", _e)

except Exception as e:
    import logging
    logging.getLogger("compat").warning("compat patch (balance/timesync) failed: %s", e)
# === /COMPAT PATCH ===

# --- COMPAT: GLOBAL SIG GUARD (builtins, idempotent) ---
import builtins as _blt
for _nm in ("sig", "signal", "trade_signal"):
    if not hasattr(_blt, _nm):
        setattr(_blt, _nm, None)

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
        # -- removed recursive _patched_init --
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

# --- IMBA SAFE INIT PATCH (idempotent, anti-recursion) ---
try:
    import logging, importlib
    _lg = logging.getLogger("compat")
    _mod = importlib.import_module("exchange.client")
    _B = getattr(_mod, "BinanceClient", None)
    if _B is not None:
        # Удаляем прежние рекурсивные обёртки: заменяем __init__ на безопасную,
        # где "оригинал" определяется как __imba_orig_init__ или текущий __init__ без повторной ребайндной цепочки.
        _orig = getattr(_B.__init__, "__imba_orig_init__", _B.__init__)
        def __imba_init__(self, *a, **k):
            # Если уже есть "настоящий" original — вызываем его; иначе просто исполняем как есть
            return _orig(self, *a, **k)
        __imba_init__.__imba_orig_init__ = _orig
        if not getattr(_B, "__imba_init_patched__", False) or getattr(_B.__init__, "__name__", "") != "__imba_init__":
            _B.__init__ = __imba_init__
            _B.__imba_init_patched__ = True
            _lg.info("compat: BinanceClient.__init__ patched safely (idempotent)")
        else:
            _lg.info("compat: BinanceClient.__init__ already safe")
except Exception as _e:
    import logging
    logging.getLogger("compat").warning("compat: SAFE INIT PATCH failed: %s", _e)
