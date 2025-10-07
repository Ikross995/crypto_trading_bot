"""
core.utils
==========

Единый набор утилит проекта с безопасными заглушками и обратной совместимостью.

В этом модуле объединены и аккуратно расширены ваши исходные утилиты
с добавлением недостающих функций/паттернов, ожидаемых другими слоями:

- Numba-совместимость: HAS_NUMBA, jit, njit, prange (если numba нет — no-op).
- Безопасные sklearn-компоненты: sklearn_components — работает и как dict, и как объект.
- Нормализация символов: normalize_symbol (+ validate_symbol_format).
- Кэш фильтров точности по символам + сеточное округление:
  update_symbol_filters(...) (поддерживает 2 сигнатуры),
  get_symbol_filters_tuple(symbol) -> (tick, step, min_notional),
  get_symbol_filters_dict(symbol) -> dict,
  round_price/round_qty (symbol-aware, «вниз» по сетке),
  fmt_price/fmt_qty.
- Финансовые/форматные хелперы и прочие утилиты из вашего файла.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict, List, Optional, Tuple, Iterable, Mapping, Union

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# Numba compatibility layer (safe fallbacks)
# ---------------------------------------------------------------------
try:
    import numba  # type: ignore
    from numba import jit as _numba_jit  # type: ignore
    from numba import njit as _numba_njit  # type: ignore
    from numba import prange as _numba_prange  # type: ignore

    HAS_NUMBA: bool = True

    def jit(*jit_args, **jit_kwargs):
        """Numba jit с безопасными дефолтами."""
        if "nopython" not in jit_kwargs:
            jit_kwargs["nopython"] = True
        if "cache" not in jit_kwargs:
            jit_kwargs["cache"] = True
        return _numba_jit(*jit_args, **jit_kwargs)

    def njit(*jit_args, **jit_kwargs):
        if "cache" not in jit_kwargs:
            jit_kwargs["cache"] = True
        return _numba_njit(*jit_args, **jit_kwargs)

    def prange(*args, **kwargs):
        return _numba_prange(*args, **kwargs)

except Exception:  # numba отсутствует — даём заглушки
    HAS_NUMBA: bool = False

    def jit(*jit_args, **jit_kwargs):
        """No-op jit: возвращает функцию без компиляции."""
        if jit_args and callable(jit_args[0]) and len(jit_args) == 1 and not jit_kwargs:
            return jit_args[0]
        def _decorator(fn):
            return fn
        return _decorator

    def njit(*jit_args, **jit_kwargs):
        return jit(*jit_args, **jit_kwargs)

    def prange(*args, **kwargs):
        return range(*args, **kwargs)

# ---------------------------------------------------------------------
# sklearn safe container (для data.preprocessing ожидается индексатор)  # :contentReference[oaicite:4]{index=4}
# ---------------------------------------------------------------------
class _IdentityScaler:
    def fit(self, X, y=None): return self
    def transform(self, X): return X
    def fit_transform(self, X, y=None): return X
    def inverse_transform(self, X): return X

class _IdentitySelector:
    def __init__(self, k=10): self.k = k
    def fit(self, X, y=None): return self
    def transform(self, X): return X
    def get_support(self, indices=False):
        import numpy as _np
        if indices: return _np.arange(0, 0, dtype=int)
        return []

def _f_regression_stub(X, y):  # совместимость с API
    import numpy as _np
    return _np.zeros(X.shape[1] if hasattr(X, "shape") else 0), None

class _SklearnComponents:
    """
    Гибрид: поддерживает и `obj['Name']`, и `obj.Name`.
    """
    def __init__(self):
        try:
            from sklearn.preprocessing import StandardScaler as _StandardScaler  # type: ignore
            from sklearn.preprocessing import MinMaxScaler as _MinMaxScaler     # type: ignore
            from sklearn.preprocessing import RobustScaler as _RobustScaler     # type: ignore
            from sklearn.feature_selection import SelectKBest as _SelectKBest   # type: ignore
            from sklearn.feature_selection import f_regression as _f_regression # type: ignore
            self._map = {
                "StandardScaler": _StandardScaler,
                "MinMaxScaler": _MinMaxScaler,
                "RobustScaler": _RobustScaler,
                "SelectKBest": _SelectKBest,
                "f_regression": _f_regression,
            }
        except Exception:
            # Фоллбэк без sklearn
            self._map = {
                "StandardScaler": _IdentityScaler,
                "MinMaxScaler": _IdentityScaler,
                "RobustScaler": _IdentityScaler,
                "SelectKBest": _IdentitySelector,
                "f_regression": _f_regression_stub,
            }

    def __getitem__(self, key: str):
        return self._map[key]

    def __getattr__(self, name: str):
        if name in self._map:
            return self._map[name]
        raise AttributeError(name)

    def get(self, key: str, default=None):
        return self._map.get(key, default)

sklearn_components = _SklearnComponents()  # используется как dict и как объект  # :contentReference[oaicite:5]{index=5}

# ---------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if s == "" or s.lower() in ("none", "null", "nan"):
            return float(default)
        return float(s)
    except Exception:
        return float(default)

def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if s == "" or s.lower() in ("none", "null", "nan"):
            return int(default)
        return int(float(s))
    except Exception:
        return int(default)

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    delay = base_delay * (2 ** max(0, int(attempt)))
    jitter = random.uniform(0.1, 0.9) * delay
    return min(max_delay, delay + jitter)

def now_ms() -> int:
    return int(time.time() * 1000)

def get_current_timestamp() -> int:
    return now_ms()

def milliseconds_to_datetime(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)

def datetime_to_milliseconds(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)

# ---------------------------------------------------------------------
# Symbols normalization
# ---------------------------------------------------------------------

def normalize_symbol(symbol: str) -> str:
    """
    Привести символ к UM Futures формату.
    - Убирает '/', '-', '_' и пробелы.
    - Верхний регистр.
    - Автосуффикс USDT для распространённых баз, если без суффикса.
    Примеры: 'btc' -> 'BTCUSDT', 'ETH/USDT' -> 'ETHUSDT', 'SOL' -> 'SOLUSDT'.
    """
    if not symbol:
        return ""
    s = str(symbol).upper().strip().replace("/", "").replace("-", "").replace("_", "").replace(" ", "")
    base_map = {
        "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "ADA": "ADAUSDT",
        "DOT": "DOTUSDT", "LINK": "LINKUSDT", "UNI": "UNIUSDT", "AVAX": "AVAXUSDT",
        "MATIC": "MATICUSDT", "ATOM": "ATOMUSDT", "BNB": "BNBUSDT", "LTC": "LTCUSDT",
    }
    if s in base_map:
        return base_map[s]
    if not s.endswith(("USDT", "BUSD", "USDC")) and len(s) >= 3:
        s = s + "USDT"
    return s

def validate_symbol_format(symbol: str) -> bool:
    try:
        n = normalize_symbol(symbol)
        return len(n) >= 6 and n.isalnum()
    except Exception:
        return False

# ---------------------------------------------------------------------
# Precision cache & rounding helpers (symbol-aware, для exchange.orders)  # :contentReference[oaicite:6]{index=6}
# ---------------------------------------------------------------------

# Кэш: {SYMBOL: {"tick": .., "step": .., "min_notional": ..}}
_SYMBOL_FILTERS: Dict[str, Dict[str, float]] = {}

def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    v = Decimal(str(value))
    q = Decimal(str(step))
    # (value // step) * step  — всегда вниз по сетке
    return float((v / q).to_integral_value(rounding=ROUND_FLOOR) * q)

def _decimals_from_step(step: float) -> int:
    if step <= 0:
        return 8
    if step >= 1:
        return 0
    return max(0, int(round(-math.log10(step))))

def update_symbol_filters(arg1, *args, **kwargs):
    """
    Совмещённая функция для двух сигнатур:

    1) Новый паттерн, ожидаемый ордерным слоем:
       update_symbol_filters(symbol: str, tick: float, step: float, min_notional: float)

    2) Ваш прежний паттерн (dict):
       update_symbol_filters(symbol_info: dict, symbol: str = "")
       -> возвращает нормализованный dict-фильтр (оставлен для совместимости).

    Обе ветки обновляют внутренний кэш _SYMBOL_FILTERS, если известны symbol/tick/step/min_notional.
    """
    # Ветка №2: словарь с фильтрами, совместимость с вашим старым кодом:
    if isinstance(arg1, Mapping):
        symbol_info: Mapping[str, Any] = arg1
        symbol = kwargs.get("symbol") or symbol_info.get("symbol") or "UNKNOWN"
        filters = {
            'symbol': symbol,
            'status': symbol_info.get('status', 'TRADING'),
            'baseAsset': symbol_info.get('baseAsset', ''),
            'quoteAsset': symbol_info.get('quoteAsset', ''),
            'minPrice': safe_float(symbol_info.get('minPrice', 0.0)),
            'maxPrice': safe_float(symbol_info.get('maxPrice', float('inf'))),
            'tickSize': 0.01,
            'minQty': 0.0001,
            'maxQty': float('inf'),
            'stepSize': 0.0001,
            'minNotional': 0.0,
            'maxNotional': float('inf'),
        }
        symbol_filters = symbol_info.get('filters', [])
        if isinstance(symbol_filters, list):
            for f in symbol_filters:
                if not isinstance(f, Mapping):
                    continue
                ft = f.get('filterType', '')
                if ft == 'PRICE_FILTER':
                    filters['tickSize'] = safe_float(f.get('tickSize', 0.01))
                elif ft == 'LOT_SIZE':
                    filters['stepSize'] = safe_float(f.get('stepSize', 0.0001))
                    filters['minQty'] = safe_float(f.get('minQty', 0.0001))
                elif ft in ('MIN_NOTIONAL', 'NOTIONAL'):
                    filters['minNotional'] = safe_float(f.get('minNotional', f.get('notional', 0.0)))
        # Обновим кэш, если всё есть
        if symbol and filters['tickSize'] > 0 and filters['stepSize'] > 0:
            _SYMBOL_FILTERS[str(symbol).upper()] = {
                "tick": float(filters['tickSize']),
                "step": float(filters['stepSize']),
                "min_notional": float(filters['minNotional']),
            }
        return filters

    # Ветка №1: новая сигнатура
    symbol: str = str(arg1)
    try:
        tick, step, mn = float(args[0]), float(args[1]), float(args[2])
    except Exception:
        # Пытаемся вытащить по именованным
        tick = float(kwargs.get("tick", kwargs.get("tick_size", 0.01)))
        step = float(kwargs.get("step", kwargs.get("step_size", 0.001)))
        mn   = float(kwargs.get("min_notional", kwargs.get("min_notional_usdt", 5.0)))

    if not symbol:
        return
    _SYMBOL_FILTERS[str(symbol).upper()] = {
        "tick": float(tick or 0.01),
        "step": float(step or 0.001),
        "min_notional": float(mn or 5.0),
    }

def get_symbol_filters_tuple(symbol: str) -> Tuple[float, float, float]:
    """Вернёт (tick, step, min_notional) для symbol (или дефолты)."""
    f = _SYMBOL_FILTERS.get(str(symbol).upper(), {}) if symbol else {}
    tick = float(f.get("tick", 0.01) or 0.01)
    step = float(f.get("step", 0.001) or 0.001)
    mn   = float(f.get("min_notional", 5.0) or 5.0)
    return tick, step, mn

def get_symbol_filters_dict(symbol: str) -> Dict[str, Any]:
    """Dict-представление фильтров (обратная совместимость с вашим кодом)."""
    tick, step, mn = get_symbol_filters_tuple(symbol)
    return {
        'symbol': symbol,
        'status': 'TRADING',
        'baseAsset': symbol.replace('USDT', ''),
        'quoteAsset': 'USDT' if 'USDT' in symbol else 'BUSD' if 'BUSD' in symbol else 'USD',
        'minPrice': 0.0,
        'maxPrice': float('inf'),
        'tickSize': tick,
        'minQty': 0.0,
        'maxQty': float('inf'),
        'stepSize': step,
        'minNotional': mn,
        'maxNotional': float('inf'),
    }

# Для совместимости с вашим прежним API:
def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    return get_symbol_filters_dict(symbol)

def round_price(symbol: str, price: float, tick_size: Optional[float] = None) -> float:
    """
    Округлить цену ВНИЗ к сетке биржи (в отличие от обычного round(...)).
    Это безопаснее для лимитов/стопов и согласовано с ордерным слоем.  # :contentReference[oaicite:7]{index=7}
    """
    tick, _, _ = get_symbol_filters_tuple(symbol)
    ts = float(tick_size) if tick_size is not None else tick
    return _floor_to_step(float(price), float(ts))

def round_qty(symbol: str, qty: float, step_size: Optional[float] = None) -> float:
    """Округлить количество ВНИЗ к шагу LOT_SIZE."""
    _, step, _ = get_symbol_filters_tuple(symbol)
    ss = float(step_size) if step_size is not None else step
    return _floor_to_step(abs(float(qty)), float(ss))

# Алиасы для старого кода (без symbol)
def round_quantity(quantity: float, step_size: float = 0.001) -> float:
    """Alias (без symbol). Лучше использовать round_qty(symbol, qty, step)."""
    return _floor_to_step(abs(float(quantity)), float(step_size))

def round_price_simple(price: float, tick_size: float = 0.01) -> float:
    """Alias к round_price без symbol (оставлен для старых мест)."""
    return _floor_to_step(float(price), float(tick_size))

def get_precision_from_stepsize(step_size: str | float) -> int:
    """Подсчитать количество знаков после запятой по stepSize."""
    s = str(step_size)
    if "." in s:
        return max(0, len(s.split(".")[1].rstrip("0")))
    return 0

def fmt_price(symbol: str, price: float, tick_size: Optional[float] = None) -> str:
    tick, _, _ = get_symbol_filters_tuple(symbol)
    ts = float(tick_size) if tick_size is not None else tick
    d = _decimals_from_step(ts)
    p = round_price(symbol, price, ts)
    return f"{p:.{d}f}"

def fmt_qty(symbol: str, qty: float, step_size: Optional[float] = None) -> str:
    _, step, _ = get_symbol_filters_tuple(symbol)
    ss = float(step_size) if step_size is not None else step
    d = _decimals_from_step(ss)
    q = round_qty(symbol, qty, ss)
    return f"{q:.{d}f}"

# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------

def format_currency(amount: float, currency: str = "USDT", decimals: int = 2) -> str:
    try:
        return f"{float(amount):,.{int(decimals)}f} {currency}"
    except Exception:
        return f"{amount} {currency}"

def format_percentage(value: float, decimals: int = 2) -> str:
    try:
        return f"{float(value):.{int(decimals)}f}%"
    except Exception:
        return f"{value}%"

def format_price_value(price: float, precision: int = 2) -> str:
    return f"{float(price):.{int(precision)}f}"

def format_time_duration(seconds: float) -> str:
    s = float(seconds)
    if s < 60: return f"{s:.1f}s"
    if s < 3600: return f"{s/60:.1f}m"
    if s < 86400: return f"{s/3600:.1f}h"
    return f"{s/86400:.1f}d"

def format_timestamp(ts: datetime | int | float, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if isinstance(ts, (int, float)):
        t = float(ts)
        if t > 1e10:  # мс
            t = t / 1000.0
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
    else:
        dt = ts
    return dt.strftime(fmt)

# ---------------------------------------------------------------------
# PnL & sizes (universal)
# ---------------------------------------------------------------------

def calculate_pnl(*args, **kwargs) -> float:
    """
    Универсальный расчёт PnL.
    - Вариант А: calculate_pnl(position_obj) — если первый аргумент объект позиции.
      Использует .realized_pnl/closed_pnl если есть; иначе пытается из entry/exit/size.
    - Вариант Б: calculate_pnl(entry_price, current_price, quantity, side="LONG")
      side: "LONG"|"SHORT"
    Возвращает PnL в котируемой валюте.
    """
    if not args:
        return 0.0

    # Вариант А — объект позиции
    pos = args[0]
    if hasattr(pos, "symbol") and (hasattr(pos, "size") or hasattr(pos, "qty")):
        for k in ("realized_pnl", "realizedPnL", "pnl", "closed_pnl"):
            if hasattr(pos, k):
                try:
                    return float(getattr(pos, k))
                except Exception:
                    pass
        try:
            size = float(getattr(pos, "size", getattr(pos, "qty")))
            entry = float(getattr(pos, "entry_price"))
            exit_px = getattr(pos, "exit_price", None)
            if exit_px is None:
                return 0.0
            exit_px = float(exit_px)
            return (exit_px - entry) * size if size >= 0 else (entry - exit_px) * abs(size)
        except Exception:
            return 0.0

    # Вариант Б — числа
    if len(args) >= 3:
        entry_price = safe_float(args[0], 0.0)
        current_price = safe_float(args[1], 0.0)
        quantity = safe_float(args[2], 0.0)
        side = str(kwargs.get("side", "LONG")).upper()
        if side == "LONG":
            return (current_price - entry_price) * quantity
        else:
            return (entry_price - current_price) * quantity

    return 0.0

def calculate_position_size(
    account_balance: float,
    risk_percentage: float,
    entry_price: float,
    stop_price: float,
    leverage: int = 1
) -> float:
    """
    Размер позиции из риска на сделку.
    risk_percentage — доля, 0.01 = 1%.
    """
    entry_price = float(entry_price); stop_price = float(stop_price)
    if entry_price <= 0 or stop_price <= 0: return 0.0
    risk_amount = float(account_balance) * float(risk_percentage)
    price_diff = abs(entry_price - stop_price)
    if price_diff <= 0: return 0.0
    return max(0.0, (risk_amount * max(1, int(leverage))) / price_diff)

def calculate_position_size_pct(
    balance: float, 
    risk_percentage_pct: float, 
    entry_price: float, 
    stop_loss_price: float,
    leverage: int = 1
) -> float:
    """
    Вариант как в части вашего кода: риск передаётся в процентах (напр. 0.5 -> 0.5%).
    """
    risk_amount = float(balance) * (float(risk_percentage_pct) / 100.0)
    price_difference = abs(float(entry_price) - float(stop_loss_price))
    if price_difference == 0:
        return 0.0
    return (risk_amount * max(1, int(leverage))) / price_difference

def calculate_percentage_change(old_value: float, new_value: float) -> float:
    if old_value == 0: return 0.0
    return ((float(new_value) - float(old_value)) / float(old_value)) * 100.0

def calculate_sharpe_ratio(returns: Iterable[float], risk_free_rate: float = 0.0) -> float:
    arr = [float(x) for x in (returns or [])]
    if len(arr) < 2: return 0.0
    import statistics
    mean = statistics.mean(arr) - float(risk_free_rate)
    stdev = statistics.pstdev(arr) or 0.0
    return (mean / stdev) if stdev else 0.0

def calculate_max_drawdown(equity_curve: Iterable[float]) -> Tuple[float, float]:
    vals = [float(x) for x in (equity_curve or [])]
    if len(vals) < 2: return 0.0, 0.0
    peak = vals[0]; max_dd_abs = 0.0; max_dd_pct = 0.0
    for v in vals[1:]:
        if v > peak: peak = v
        dd_abs = peak - v
        dd_pct = (dd_abs / peak * 100.0) if peak > 0 else 0.0
        if dd_abs > max_dd_abs: max_dd_abs = dd_abs
        if dd_pct > max_dd_pct: max_dd_pct = dd_pct
    return max_dd_abs, max_dd_pct

# ---------------------------------------------------------------------
# Misc, legacy aliases и совместимость имён из вашего файла
# ---------------------------------------------------------------------

def format_price(price: float, precision: int = 2) -> str:
    """Старый алиас (совместимость)."""
    return format_price_value(price, precision)

def round_qty_alias(quantity: float, step_size: float = 0.001) -> float:
    """Алиас для старого имени round_quantity."""
    return round_quantity(quantity, step_size)

# Явные экспорты
__all__ = [
    # numba
    "HAS_NUMBA", "jit", "njit", "prange",
    # sklearn
    "sklearn_components",
    # symbol/precision
    "normalize_symbol", "validate_symbol_format",
    "update_symbol_filters", "get_symbol_filters", "get_symbol_filters_tuple", "get_symbol_filters_dict",
    "round_price", "round_qty", "round_quantity", "round_price_simple",
    "fmt_price", "fmt_qty", "get_precision_from_stepsize",
    # base helpers
    "safe_float", "safe_int", "clamp", "exponential_backoff",
    "now_ms", "get_current_timestamp", "milliseconds_to_datetime", "datetime_to_milliseconds",
    # formatting & pnl & sizes
    "format_currency", "format_percentage", "format_price", "format_price_value", "format_time_duration", "format_timestamp",
    "calculate_pnl",
    "calculate_position_size", "calculate_position_size_pct",
    "calculate_percentage_change", "calculate_sharpe_ratio", "calculate_max_drawdown",
]


def validate_symbol(sym: str) -> str:
    try:
        return str(sym).strip().upper()
    except Exception:
        return ""


def csv_to_list(val):
    if not val:
        return []
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    raw = str(val)
    parts = [x.strip() for x in raw.replace(" ", "").split(",") if x.strip()]
    return parts


def ensure_attr(obj, name, default):
    try:
        return getattr(obj, name)
    except Exception:
        try:
            setattr(obj, name, default)
        except Exception:
            pass
        return default
