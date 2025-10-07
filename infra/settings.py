# infra/settings.py
# Загрузка профилей и горячих оверрайдов настроек. Без внешних зависимостей.

from __future__ import annotations
import os, time, configparser
from typing import Dict, Any, List, Tuple

# ---- Ключи и их отображение в атрибуты конфига (config.<attr>) ----
KEY_MAP = {
    # Trading Parameters
    "SYMBOL": "symbol",
    "SYMBOLS": "symbols",
    "TIMEFRAME": "timeframe",
    "BACKTEST_DAYS": "backtest_days",

    # Risk
    "LEVERAGE": "leverage",
    "RISK_PER_TRADE_PCT": "risk_per_trade",      # в долях (0.005 для 0.5%)
    "MAX_DAILY_LOSS_PCT": "max_daily_loss",      # в долях (0.05 для 5%)
    "MAX_DRAWDOWN_PCT": "max_drawdown",          # в долях
    "MIN_NOTIONAL_USDT": "min_notional",
    "TAKER_FEE": "taker_fee",
    "MAKER_FEE": "maker_fee",
    "SLIPPAGE_BPS": "slippage_bps",              # 1 bp=0.0001

    # Signal
    "MIN_ADX": "min_adx",
    "BT_CONF_MIN": "bt_conf_min",
    "BT_BBW_MIN": "bt_bbw_min",
    "COOLDOWN_SEC": "cooldown_sec",
    "ANTI_FLIP_SEC": "anti_flip_sec",
    "VWAP_BAND_PCT": "vwap_band_pct",
    "EMA_PINCH_Q": "ema_pinch_q",

    # DCA
    "DCA_LADDER": "dca_ladder",                  # "-0.6:1.0,-1.2:1.5" (% и множитель)
    "ADAPTIVE_DCA": "adaptive_dca",
    "DCA_TREND_ADX": "dca_trend_adx",
    "DCA_DISABLE_ON_TREND": "dca_disable_on_trend",

    # Stops & TP
    "SL_FIXED_PCT": "sl_fixed_pct",              # в долях (1.0% => 0.01)
    "SL_ATR_MULT": "sl_atr_mult",
    "TP_LEVELS": "tp_levels",
    "TP_SHARES": "tp_shares",
    "BE_TRIGGER_R": "be_trigger_r",
    "TRAIL_ENABLE": "trail_enable",
    "TRAIL_ATR_MULT": "trail_atr_mult",

    # Exits on exchange
    "PLACE_EXITS_ON_EXCHANGE": "place_exits_on_exchange",
    "EXIT_WORKING_TYPE": "exit_working_type",
    "EXIT_REPLACE_EPS": "exit_replace_eps",
    "EXIT_REPLACE_COOLDOWN": "exit_replace_cooldown",
    "MIN_TP_NOTIONAL_USDT": "min_tp_notional",
    "EXITS_ENSURE_INTERVAL": "exits_ensure_interval",

    # ML / GPT
    "LSTM_ENABLE": "lstm_enable",
    "LSTM_INPUT": "lstm_input",
    "SEQ_LEN": "seq_len",
    "LSTM_SIGNAL_THRESHOLD": "lstm_signal_threshold",

    "GPT_ENABLE": "gpt_enable",
    "GPT_API_URL": "gpt_api_url",
    "GPT_MODEL": "gpt_model",
    "GPT_MAX_TOKENS": "gpt_max_tokens",
    "GPT_INTERVAL": "gpt_interval",
    "GPT_TIMEOUT": "gpt_timeout",

    # WebSocket
    "WS_ENABLE": "ws_enable",
    "WS_DEPTH_LEVEL": "ws_depth_level",
    "WS_DEPTH_INTERVAL": "ws_depth_interval",
    "OBI_ALPHA": "obi_alpha",
    "OBI_THRESHOLD": "obi_threshold",

    # Files
    "KL_PERSIST": "kl_persist",
    "TRADES_PATH": "trades_path",
    "EQUITY_PATH": "equity_path",
    "RESULTS_PATH": "results_path",
    "STATE_PATH": "state_path",
}

# ---- какие *_PCT НЕ делим на 100 (они уже в долях) ----
PCT_ALREADY_FRACTION = {"VWAP_BAND_PCT"}
# какие *_PCT точно нужно делить (даже если значение <= 1.0)
PCT_FORCE_DIV100 = {"RISK_PER_TRADE_PCT", "MAX_DAILY_LOSS_PCT", "SL_FIXED_PCT", "MAX_DRAWDOWN_PCT"}

def _parse_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1","true","yes","on","y","t"}

def _parse_list(v: str) -> List[str]:
    return [s.strip() for s in str(v).split(",") if s.strip()]

def _parse_float(v: str) -> float:
    return float(str(v).strip())

def _parse_tp_list(v: str) -> List[float]:
    return [float(x.strip()) for x in str(v).split(",") if x.strip()]

def _parse_dca_ladder(v: str) -> List[Tuple[float,float]]:
    # "-0.6:1.0,-1.2:1.5" => [(-0.006,1.0), (-0.012,1.5)]
    out: List[Tuple[float,float]] = []
    for part in str(v).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        off_s, mult_s = part.split(":", 1)
        off = float(off_s.strip())
        mult = float(mult_s.strip())
        off_frac = off / 100.0
        out.append((off_frac, mult))
    return out

def _coerce(key: str, raw: str) -> Any:
    k = key.strip().upper()
    val = raw.strip()

    if k == "SYMBOLS":
        return _parse_list(val)
    if k in {"LEVERAGE","BACKTEST_DAYS","WS_DEPTH_LEVEL","WS_DEPTH_INTERVAL",
             "LSTM_INPUT","SEQ_LEN","GPT_MAX_TOKENS","GPT_INTERVAL","GPT_TIMEOUT",
             "COOLDOWN_SEC","ANTI_FLIP_SEC","EXIT_REPLACE_COOLDOWN",
             "EXITS_ENSURE_INTERVAL"}:
        return int(float(val))
    if k in {"TAKER_FEE","MAKER_FEE","OBI_ALPHA","OBI_THRESHOLD","LSTM_SIGNAL_THRESHOLD",
             "BT_CONF_MIN","BT_BBW_MIN","MIN_ADX","DCA_TREND_ADX","EXIT_REPLACE_EPS",
             "MIN_TP_NOTIONAL_USDT","MIN_NOTIONAL_USDT","EMA_PINCH_Q"}:
        return _parse_float(val)
    if k in {"WS_ENABLE","LSTM_ENABLE","GPT_ENABLE","TRAIL_ENABLE",
             "ADAPTIVE_DCA","DCA_DISABLE_ON_TREND","PLACE_EXITS_ON_EXCHANGE"}:
        return _parse_bool(val)
    if k == "TP_LEVELS":
        return _parse_tp_list(val)
    if k == "TP_SHARES":
        shares = _parse_tp_list(val)
        s = sum(shares) or 1.0
        return [x/s for x in shares]
    if k == "DCA_LADDER":
        return _parse_dca_ladder(val)
    if k.endswith("_PCT"):
        x = _parse_float(val)
        if k in PCT_ALREADY_FRACTION:
            return x
        if k in PCT_FORCE_DIV100 or x > 1.0:
            return x / 100.0
        return x
    if k == "SLIPPAGE_BPS":
        return _parse_float(val) / 10000.0
    return val

def _kmap(key: str) -> str:
    k = key.strip().upper()
    return KEY_MAP.get(k, k.lower())

def parse_kv_dict(raw_dict: Dict[str,str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in raw_dict.items():
        if v is None:
            continue
        out[_kmap(k)] = _coerce(k, str(v))
    return out

# ---------- Профили в INI ----------
def load_profile(profile_name: str, ini_path: str = "config/profiles.ini") -> Dict[str, Any]:
    if not os.path.exists(ini_path):
        return {}
    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # сохранить регистр ключей
    cfg.read(ini_path, encoding="utf-8")
    if profile_name not in cfg.sections():
        return {}
    section = cfg[profile_name]
    raw = {k: section.get(k) for k in section}
    return parse_kv_dict(raw)

# ---------- Оверрайды из файла с командами :set ----------
def load_overrides(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    changes: Dict[str, Any] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith(":set"):
                body = s[4:].strip()
                if " " not in body:
                    continue
                key, val = body.split(None, 1)
                changes[_kmap(key)] = _coerce(key, val)
    return changes

def apply_settings_to_config(config: Any, settings: Dict[str, Any]) -> None:
    for attr, val in settings.items():
        try:
            setattr(config, attr, val)
        except Exception:
            pass

class RuntimeOverridesWatcher:
    """Следит за файлом overrides и возвращает изменения при обновлении."""
    def __init__(self, path: str):
        self.path = path
        self._last_mtime = 0.0

    def poll(self) -> Dict[str, Any]:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return {}
        if st.st_mtime <= self._last_mtime:
            return {}
        self._last_mtime = st.st_mtime
        return load_overrides(self.path)
