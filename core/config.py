"""Configuration management for the crypto trading bot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar, List, Optional, Sequence

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

from .constants import Timeframe, TradingMode

_BOOL_TRUE = {"true", "1", "yes", "y", "on"}
_BOOL_FALSE = {"false", "0", "no", "n", "off"}
_VALID_TIMEFRAMES = {tf.value for tf in Timeframe}


def _parse_bool(value: object, default: bool) -> bool:
    """Parse truthy/falsey values from environment variables."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    return default


def _parse_float_list(value: str) -> List[float]:
    items: List[float] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        items.append(float(part))
    return items


def _parse_dca_pairs(value: str) -> List[tuple[float, float]]:
    ladder: List[tuple[float, float]] = []
    for item in value.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        level_str, multiplier_str = item.split(":", 1)
        ladder.append((float(level_str), float(multiplier_str)))
    return ladder


class Config(BaseModel):
    """Main configuration object with validation helpers."""

    env_file_default: ClassVar[Optional[Path]] = None

    # Trading mode / behaviour
    mode: TradingMode = Field(default=TradingMode.PAPER)
    dry_run: bool = Field(default=True)
    testnet: bool = Field(default=True)
    save_reports: bool = Field(default=True)

    # API credentials
    binance_api_key: str = Field(default="")
    binance_api_secret: str = Field(default="")

    # Trading parameters
    symbol: str = Field(default="BTCUSDT")
    symbols: List[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    timeframe: str = Field(default="1m")
    backtest_days: int = Field(default=90)

    # Risk management
    leverage: int = Field(default=5)
    risk_per_trade_pct: float = Field(default=0.5)
    max_daily_loss_pct: float = Field(default=5.0)
    min_notional_usdt: float = Field(default=5.0)
    taker_fee: float = Field(default=0.0004)
    maker_fee: float = Field(default=0.0002)
    slippage_bps: int = Field(default=2)

    # Signal configuration
    min_adx: float = Field(default=25.0)
    bt_conf_min: float = Field(default=0.80)
    bt_bbw_min: float = Field(default=0.0)
    cooldown_sec: int = Field(default=300)
    anti_flip_sec: int = Field(default=60)
    vwap_band_pct: float = Field(default=0.003)

    # Dollar-cost averaging
    dca_enable: bool = Field(default=True)
    dca_ladder_str: str = Field(default="-0.6:1.0,-1.2:1.5,-2.0:2.0")
    adaptive_dca: bool = Field(default=True)
    dca_trend_adx: float = Field(default=25.0)
    dca_disable_on_trend: bool = Field(default=True)

    # Stop loss / take profit
    sl_fixed_pct: float = Field(default=1.0)
    sl_atr_mult: float = Field(default=1.6)
    tp_levels: str = Field(default="0.5,1.2,2.0")
    tp_shares: str = Field(default="0.4,0.35,0.25")
    be_trigger_r: float = Field(default=1.0)
    trail_enable: bool = Field(default=True)
    trail_atr_mult: float = Field(default=1.0)

    # Exit order configuration
    place_exits_on_exchange: bool = Field(default=True)
    exit_working_type: str = Field(default="MARK_PRICE")
    exit_replace_eps: float = Field(default=0.0025)
    exit_replace_cooldown: int = Field(default=20)
    min_tp_notional_usdt: float = Field(default=5.0)
    exits_ensure_interval: int = Field(default=12)

    # Machine learning flags
    lstm_enable: bool = Field(default=False)
    lstm_input: int = Field(default=16)
    seq_len: int = Field(default=30)
    lstm_signal_threshold: float = Field(default=0.0015)

    gpt_enable: bool = Field(default=False)
    gpt_api_url: str = Field(default="http://127.0.0.1:1234")
    gpt_model: str = Field(default="openai/gpt-oss-20b")
    gpt_max_tokens: int = Field(default=160)
    gpt_interval: int = Field(default=15)
    gpt_timeout: int = Field(default=15)

    # WebSocket
    ws_enable: bool = Field(default=True)
    ws_depth_level: int = Field(default=5)
    ws_depth_interval: int = Field(default=500)
    obi_alpha: float = Field(default=0.6)
    obi_threshold: float = Field(default=0.18)

    # Notifications
    tg_bot_token: str = Field(default="")
    tg_chat_id: str = Field(default="")

    # File paths
    kl_persist: str = Field(default="data/klines.csv")
    trades_path: str = Field(default="data/trades.csv")
    equity_path: str = Field(default="data/equity.csv")
    results_path: str = Field(default="data/results.csv")
    state_path: str = Field(default="data/state.json")

    def __init__(self, **data):
        if not data:
            data = self._load_env_mapping()
        super().__init__(**data)

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("symbols", mode="before")
    @classmethod
    def parse_symbols(cls, value: object) -> List[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, Sequence):
            return [str(item).strip() for item in value if str(item).strip()]
        return ["BTCUSDT", "ETHUSDT"]

    @field_validator("exit_working_type")
    @classmethod
    def validate_working_type(cls, value: str) -> str:
        valid = {"MARK_PRICE", "CONTRACT_PRICE"}
        if value not in valid:
            raise ValueError(f"exit_working_type must be one of {sorted(valid)}")
        return value

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, value: object) -> TradingMode:
        if isinstance(value, TradingMode):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered == "paper":
                return TradingMode.PAPER
            if lowered == "live":
                return TradingMode.LIVE
            if lowered == "backtest":
                return TradingMode.BACKTEST
        raise ValueError("MODE must be one of: paper, live, backtest")

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        if value not in _VALID_TIMEFRAMES:
            raise ValueError("TIMEFRAME must be one of: " + ", ".join(sorted(_VALID_TIMEFRAMES)))
        return value

    @field_validator("risk_per_trade_pct")
    @classmethod
    def validate_risk_per_trade(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("RISK_PER_TRADE_PCT must be positive")
        return value

    @field_validator("leverage")
    @classmethod
    def validate_leverage(cls, value: int) -> int:
        if not 1 <= int(value) <= 125:
            raise ValueError("LEVERAGE must be between 1 and 125")
        return int(value)

    @model_validator(mode="after")
    def validate_take_profit_alignment(self) -> "Config":
        levels = _parse_float_list(self.tp_levels)
        shares = _parse_float_list(self.tp_shares)
        if len(levels) != len(shares):
            raise ValueError("TP_LEVELS and TP_SHARES must have same length")
        total = sum(shares)
        if abs(total - 1.0) > 1e-6:
            raise ValueError("TP_SHARES must sum to 1.0")
        return self

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    @property
    def use_lstm(self) -> bool:
        return self.lstm_enable

    @property
    def use_gpt(self) -> bool:
        return self.gpt_enable

    @property
    def use_dca(self) -> bool:
        return self.dca_enable

    @property
    def use_websocket(self) -> bool:
        return self.ws_enable

    @property
    def risk_per_trade(self) -> float:
        """Compatibility property returning risk percentage in decimal form."""
        return self.risk_per_trade_pct / 100.0

    @property
    def max_daily_loss(self) -> float:
        return self.max_daily_loss_pct

    @property
    def close_positions_on_exit(self) -> bool:
        return True

    @property
    def dca_ladder(self) -> List[tuple[float, float]]:
        return self.parse_dca_ladder()

    def has_api_credentials(self) -> bool:
        return bool(self.binance_api_key and self.binance_api_secret)

    def validate_api_credentials(self) -> bool:
        if not self.binance_api_key:
            raise ValueError("BINANCE_API_KEY is required")
        if not self.binance_api_secret:
            raise ValueError("BINANCE_API_SECRET is required")
        return True

    def parse_dca_ladder(self) -> List[tuple[float, float]]:
        return _parse_dca_pairs(self.dca_ladder_str)

    def parse_tp_levels(self) -> List[float]:
        return _parse_float_list(self.tp_levels)

    def parse_tp_shares(self) -> List[float]:
        return _parse_float_list(self.tp_shares)

    # ------------------------------------------------------------------
    # Environment handling
    # ------------------------------------------------------------------
    @classmethod
    def _load_env_mapping(cls, env_file: Optional[str] = None) -> dict:
        env_path: Optional[Path]
        if env_file:
            env_path = Path(env_file)
        elif cls.env_file_default is not None:
            env_path = cls.env_file_default
        else:
            config_env = os.getenv("CONFIG_ENV_FILE")
            env_path = Path(config_env) if config_env else None

        if env_path and env_path.exists() and not os.getenv("PYTEST_CURRENT_TEST"):
            load_dotenv(env_path, override=False)

        def getenv(name: str, default: Optional[str] = None) -> Optional[str]:
            return os.getenv(name, default)

        def bool_env(*names: str, default: bool) -> bool:
            for name in names:
                if (raw := getenv(name)) is not None:
                    return _parse_bool(raw, default)
            return default

        mapping = {
            "mode": getenv("MODE", "paper"),
            "dry_run": bool_env("DRY_RUN", default=True),
            "testnet": bool_env("TESTNET", default=True),
            "save_reports": bool_env("SAVE_REPORTS", default=True),
            "binance_api_key": getenv("BINANCE_API_KEY", ""),
            "binance_api_secret": getenv("BINANCE_API_SECRET", ""),
            "symbol": getenv("SYMBOL", "BTCUSDT"),
            "symbols": getenv("SYMBOLS", "BTCUSDT,ETHUSDT"),
            "timeframe": getenv("TIMEFRAME", "1m"),
            "backtest_days": int(getenv("BACKTEST_DAYS", "90")),
            "leverage": int(getenv("LEVERAGE", "5")),
            "risk_per_trade_pct": float(getenv("RISK_PER_TRADE_PCT", "0.5")),
            "max_daily_loss_pct": float(getenv("MAX_DAILY_LOSS_PCT", "5.0")),
            "min_notional_usdt": float(getenv("MIN_NOTIONAL_USDT", "5.0")),
            "taker_fee": float(getenv("TAKER_FEE", "0.0004")),
            "maker_fee": float(getenv("MAKER_FEE", "0.0002")),
            "slippage_bps": int(getenv("SLIPPAGE_BPS", "2")),
            "min_adx": float(getenv("MIN_ADX", "25.0")),
            "bt_conf_min": float(getenv("BT_CONF_MIN", "0.80")),
            "bt_bbw_min": float(getenv("BT_BBW_MIN", "0.0")),
            "cooldown_sec": int(getenv("COOLDOWN_SEC", "300")),
            "anti_flip_sec": int(getenv("ANTI_FLIP_SEC", "60")),
            "vwap_band_pct": float(getenv("VWAP_BAND_PCT", "0.003")),
            "dca_enable": bool_env("USE_DCA", "DCA_ENABLE", default=True),
            "dca_ladder_str": getenv("DCA_LADDER", "-0.6:1.0,-1.2:1.5,-2.0:2.0"),
            "adaptive_dca": bool_env("ADAPTIVE_DCA", default=True),
            "dca_trend_adx": float(getenv("DCA_TREND_ADX", "25.0")),
            "dca_disable_on_trend": bool_env("DCA_DISABLE_ON_TREND", default=True),
            "sl_fixed_pct": float(getenv("SL_FIXED_PCT", "1.0")),
            "sl_atr_mult": float(getenv("SL_ATR_MULT", "1.6")),
            "tp_levels": getenv("TP_LEVELS", "0.5,1.2,2.0"),
            "tp_shares": getenv("TP_SHARES", "0.4,0.35,0.25"),
            "be_trigger_r": float(getenv("BE_TRIGGER_R", "1.0")),
            "trail_enable": bool_env("TRAIL_ENABLE", default=True),
            "trail_atr_mult": float(getenv("TRAIL_ATR_MULT", "1.0")),
            "place_exits_on_exchange": bool_env("PLACE_EXITS_ON_EXCHANGE", default=True),
            "exit_working_type": getenv("EXIT_WORKING_TYPE", "MARK_PRICE"),
            "exit_replace_eps": float(getenv("EXIT_REPLACE_EPS", "0.0025")),
            "exit_replace_cooldown": int(getenv("EXIT_REPLACE_COOLDOWN", "20")),
            "min_tp_notional_usdt": float(getenv("MIN_TP_NOTIONAL_USDT", "5.0")),
            "exits_ensure_interval": int(getenv("EXITS_ENSURE_INTERVAL", "12")),
            "lstm_enable": bool_env("USE_LSTM", "LSTM_ENABLE", default=False),
            "lstm_input": int(getenv("LSTM_INPUT", "16")),
            "seq_len": int(getenv("SEQ_LEN", "30")),
            "lstm_signal_threshold": float(getenv("LSTM_SIGNAL_THRESHOLD", "0.0015")),
            "gpt_enable": bool_env("USE_GPT", "GPT_ENABLE", default=False),
            "gpt_api_url": getenv("GPT_API_URL", "http://127.0.0.1:1234"),
            "gpt_model": getenv("GPT_MODEL", "openai/gpt-oss-20b"),
            "gpt_max_tokens": int(getenv("GPT_MAX_TOKENS", "160")),
            "gpt_interval": int(getenv("GPT_INTERVAL", "15")),
            "gpt_timeout": int(getenv("GPT_TIMEOUT", "15")),
            "ws_enable": bool_env("USE_WEBSOCKET", "WS_ENABLE", default=True),
            "ws_depth_level": int(getenv("WS_DEPTH_LEVEL", "5")),
            "ws_depth_interval": int(getenv("WS_DEPTH_INTERVAL", "500")),
            "obi_alpha": float(getenv("OBI_ALPHA", "0.6")),
            "obi_threshold": float(getenv("OBI_THRESHOLD", "0.18")),
            "tg_bot_token": getenv("TG_BOT_TOKEN", ""),
            "tg_chat_id": getenv("TG_CHAT_ID", ""),
            "kl_persist": getenv("KL_PERSIST", "data/klines.csv"),
            "trades_path": getenv("TRADES_PATH", "data/trades.csv"),
            "equity_path": getenv("EQUITY_PATH", "data/equity.csv"),
            "results_path": getenv("RESULTS_PATH", "data/results.csv"),
            "state_path": getenv("STATE_PATH", "data/state.json"),
        }
        return mapping

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Config":
        return cls(**cls._load_env_mapping(env_file))


_config: Optional[Config] = None


def load_config(env_file: Optional[str] = None) -> Config:
    global _config
    _config = Config.from_env(env_file)
    return _config


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config(env_file: Optional[str] = None) -> Config:
    global _config
    _config = None
    return load_config(env_file)
