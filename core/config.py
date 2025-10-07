"""
Configuration management for AI Trading Bot.
"""

import os
from pathlib import Path
from typing import Optional, List

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from .constants import TradingMode


class Config(BaseModel):
    """Main configuration class with validation and type safety."""

    # Trading Mode
    mode: TradingMode = Field(default=TradingMode.PAPER)
    dry_run: bool = Field(default=True)
    testnet: bool = Field(default=True)
    save_reports: bool = Field(default=True)

    # API Credentials
    binance_api_key: str = Field(default="")
    binance_api_secret: str = Field(default="")

    # Trading Parameters
    symbol: str = Field(default="BTCUSDT")
    symbols: List[str] = Field(default=["BTCUSDT", "ETHUSDT"])
    timeframe: str = Field(default="1m")
    backtest_days: int = Field(default=90, ge=1, le=365)

    # Risk Management
    leverage: int = Field(default=5, ge=1, le=125)
    risk_per_trade_pct: float = Field(default=0.5, ge=0.1, le=10.0)
    max_daily_loss_pct: float = Field(default=5.0, ge=1.0, le=50.0)
    min_notional_usdt: float = Field(default=5.0, ge=1.0)
    taker_fee: float = Field(default=0.0004, ge=0.0, le=0.01)
    maker_fee: float = Field(default=0.0002, ge=0.0, le=0.01)
    slippage_bps: int = Field(default=2, ge=0, le=100)

    # Signal Configuration
    min_adx: float = Field(default=25.0, ge=0.0, le=100.0)
    bt_conf_min: float = Field(default=0.80, ge=0.1, le=2.0)
    bt_bbw_min: float = Field(default=0.0, ge=0.0, le=0.1)
    cooldown_sec: int = Field(default=300, ge=0, le=3600)
    anti_flip_sec: int = Field(default=60, ge=0, le=600)
    vwap_band_pct: float = Field(default=0.003, ge=0.0, le=0.1)

    # DCA Settings
    dca_ladder_str: str = Field(default="-0.6:1.0,-1.2:1.5,-2.0:2.0")
    adaptive_dca: bool = Field(default=True)
    dca_trend_adx: float = Field(default=25.0, ge=0.0, le=100.0)
    dca_disable_on_trend: bool = Field(default=True)

    # Stop Loss & Take Profit
    sl_fixed_pct: float = Field(default=1.0, ge=0.1, le=10.0)
    sl_atr_mult: float = Field(default=1.6, ge=0.5, le=5.0)
    tp_levels: str = Field(default="0.5,1.2,2.0")
    tp_shares: str = Field(default="0.4,0.35,0.25")
    be_trigger_r: float = Field(default=1.0, ge=0.0, le=5.0)
    trail_enable: bool = Field(default=True)
    trail_atr_mult: float = Field(default=1.0, ge=0.1, le=3.0)

    # Exit Orders
    place_exits_on_exchange: bool = Field(default=True)
    exit_working_type: str = Field(default="MARK_PRICE")
    exit_replace_eps: float = Field(default=0.0025, ge=0.0, le=0.1)
    exit_replace_cooldown: int = Field(default=20, ge=5, le=300)
    min_tp_notional_usdt: float = Field(default=5.0, ge=1.0)
    exits_ensure_interval: int = Field(default=12, ge=5, le=60)

    # ML Models
    lstm_enable: bool = Field(default=False)
    lstm_input: int = Field(default=16, ge=1, le=100)
    seq_len: int = Field(default=30, ge=10, le=200)
    lstm_signal_threshold: float = Field(default=0.0015, ge=0.0001, le=0.01)

    gpt_enable: bool = Field(default=False)
    gpt_api_url: str = Field(default="http://127.0.0.1:1234")
    gpt_model: str = Field(default="openai/gpt-oss-20b")
    gpt_max_tokens: int = Field(default=160, ge=50, le=1000)
    gpt_interval: int = Field(default=15, ge=5, le=300)
    gpt_timeout: int = Field(default=15, ge=5, le=60)

    # WebSocket
    ws_enable: bool = Field(default=True)
    ws_depth_level: int = Field(default=5, ge=1, le=20)
    ws_depth_interval: int = Field(default=500, ge=100, le=3000)
    obi_alpha: float = Field(default=0.6, ge=0.1, le=1.0)
    obi_threshold: float = Field(default=0.18, ge=0.01, le=1.0)

    # Notifications
    tg_bot_token: str = Field(default="")
    tg_chat_id: str = Field(default="")

    # File Paths
    kl_persist: str = Field(default="data/klines.csv")
    trades_path: str = Field(default="data/trades.csv")
    equity_path: str = Field(default="data/equity.csv")
    results_path: str = Field(default="data/results.csv")
    state_path: str = Field(default="data/state.json")

    # Feature flags (aliases for compatibility)
    @property
    def use_lstm(self) -> bool:
        return self.lstm_enable

    @property
    def use_gpt(self) -> bool:
        return self.gpt_enable

    @property
    def use_dca(self) -> bool:
        return True  # DCA is always available

    @property
    def use_websocket(self) -> bool:
        return self.ws_enable
    
    @property
    def risk_per_trade(self) -> float:
        """Compatibility property for risk_per_trade_pct."""
        return self.risk_per_trade_pct / 100.0  # Convert percentage to decimal

    @property
    def max_daily_loss(self) -> float:
        """Get max daily loss for compatibility."""
        return self.max_daily_loss_pct

    @property
    def close_positions_on_exit(self) -> bool:
        """Whether to close positions on bot exit."""
        return True  # Default behavior

    @property
    def dca_ladder(self) -> List[tuple[float, float]]:
        """Get parsed DCA ladder for compatibility with tests."""
        return self.parse_dca_ladder()

    @field_validator("symbols", mode="before")
    @classmethod
    def parse_symbols(cls, v) -> List[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("exit_working_type")
    @classmethod
    def validate_working_type(cls, v: str) -> str:
        valid = ["MARK_PRICE", "CONTRACT_PRICE"]
        if v not in valid:
            raise ValueError(f"exit_working_type must be one of {valid}")
        return v

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v) -> TradingMode:
        if isinstance(v, str):
            v = v.lower()
            if v == "paper":
                return TradingMode.PAPER
            elif v == "live":
                return TradingMode.LIVE
            elif v == "backtest":
                return TradingMode.BACKTEST
            else:
                raise ValueError("MODE must be one of: paper, live, backtest")
        return v

    def has_api_credentials(self) -> bool:
        """Check if API credentials are configured."""
        return bool(self.binance_api_key and self.binance_api_secret)

    def parse_dca_ladder(self) -> List[tuple[float, float]]:
        """Parse DCA ladder string to list of (level_pct, multiplier) tuples."""
        ladder = []
        for item in self.dca_ladder_str.split(","):
            if ":" in item:
                level_str, mult_str = item.split(":")
                ladder.append((float(level_str.strip()), float(mult_str.strip())))
        return ladder

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Config":
        """Create config from environment variables."""
        if env_file is None:
            env_file = Path(__file__).parent.parent / ".env"

        if Path(env_file).exists():
            load_dotenv(env_file, override=True)

        # Map environment variables to pydantic fields
        env_mapping = {
            # Trading Mode
            'mode': os.getenv('MODE', 'paper'),
            'dry_run': os.getenv('DRY_RUN', 'true').lower() == 'true',
            'testnet': os.getenv('TESTNET', 'true').lower() == 'true',
            'save_reports': os.getenv('SAVE_REPORTS', 'true').lower() == 'true',

            # API Credentials
            'binance_api_key': os.getenv('BINANCE_API_KEY', ''),
            'binance_api_secret': os.getenv('BINANCE_API_SECRET', ''),

            # Trading Parameters
            'symbol': os.getenv('SYMBOL', 'BTCUSDT'),
            'symbols': os.getenv('SYMBOLS', 'BTCUSDT,ETHUSDT'),
            'timeframe': os.getenv('TIMEFRAME', '1m'),
            'backtest_days': int(os.getenv('BACKTEST_DAYS', '90')),

            # Risk Management
            'leverage': int(os.getenv('LEVERAGE', '5')),
            'risk_per_trade_pct': float(os.getenv('RISK_PER_TRADE_PCT', '0.5')),
            'max_daily_loss_pct': float(os.getenv('MAX_DAILY_LOSS_PCT', '5.0')),
            'min_notional_usdt': float(os.getenv('MIN_NOTIONAL_USDT', '5.0')),
            'taker_fee': float(os.getenv('TAKER_FEE', '0.0004')),
            'maker_fee': float(os.getenv('MAKER_FEE', '0.0002')),
            'slippage_bps': int(os.getenv('SLIPPAGE_BPS', '2')),

            # Signal Configuration
            'min_adx': float(os.getenv('MIN_ADX', '25.0')),
            'bt_conf_min': float(os.getenv('BT_CONF_MIN', '0.80')),
            'bt_bbw_min': float(os.getenv('BT_BBW_MIN', '0.0')),
            'cooldown_sec': int(os.getenv('COOLDOWN_SEC', '300')),
            'anti_flip_sec': int(os.getenv('ANTI_FLIP_SEC', '60')),
            'vwap_band_pct': float(os.getenv('VWAP_BAND_PCT', '0.003')),

            # DCA Settings
            'dca_ladder_str': os.getenv('DCA_LADDER', '-0.6:1.0,-1.2:1.5,-2.0:2.0'),
            'adaptive_dca': os.getenv('ADAPTIVE_DCA', 'true').lower() == 'true',
            'dca_trend_adx': float(os.getenv('DCA_TREND_ADX', '25.0')),
            'dca_disable_on_trend': os.getenv('DCA_DISABLE_ON_TREND', 'true').lower() == 'true',

            # Stop Loss & Take Profit
            'sl_fixed_pct': float(os.getenv('SL_FIXED_PCT', '1.0')),
            'sl_atr_mult': float(os.getenv('SL_ATR_MULT', '1.6')),
            'tp_levels': os.getenv('TP_LEVELS', '0.5,1.2,2.0'),
            'tp_shares': os.getenv('TP_SHARES', '0.4,0.35,0.25'),
            'be_trigger_r': float(os.getenv('BE_TRIGGER_R', '1.0')),
            'trail_enable': os.getenv('TRAIL_ENABLE', 'true').lower() == 'true',
            'trail_atr_mult': float(os.getenv('TRAIL_ATR_MULT', '1.0')),

            # Exit Orders
            'place_exits_on_exchange': os.getenv('PLACE_EXITS_ON_EXCHANGE', 'true').lower() == 'true',
            'exit_working_type': os.getenv('EXIT_WORKING_TYPE', 'MARK_PRICE'),
            'exit_replace_eps': float(os.getenv('EXIT_REPLACE_EPS', '0.0025')),
            'exit_replace_cooldown': int(os.getenv('EXIT_REPLACE_COOLDOWN', '20')),
            'min_tp_notional_usdt': float(os.getenv('MIN_TP_NOTIONAL_USDT', '5.0')),
            'exits_ensure_interval': int(os.getenv('EXITS_ENSURE_INTERVAL', '12')),

            # ML Models
            'lstm_enable': os.getenv('LSTM_ENABLE', 'false').lower() == 'true',
            'lstm_input': int(os.getenv('LSTM_INPUT', '16')),
            'seq_len': int(os.getenv('SEQ_LEN', '30')),
            'lstm_signal_threshold': float(os.getenv('LSTM_SIGNAL_THRESHOLD', '0.0015')),

            'gpt_enable': os.getenv('GPT_ENABLE', 'false').lower() == 'true',
            'gpt_api_url': os.getenv('GPT_API_URL', 'http://127.0.0.1:1234'),
            'gpt_model': os.getenv('GPT_MODEL', 'openai/gpt-oss-20b'),
            'gpt_max_tokens': int(os.getenv('GPT_MAX_TOKENS', '160')),
            'gpt_interval': int(os.getenv('GPT_INTERVAL', '15')),
            'gpt_timeout': int(os.getenv('GPT_TIMEOUT', '15')),

            # WebSocket
            'ws_enable': os.getenv('WS_ENABLE', 'true').lower() == 'true',
            'ws_depth_level': int(os.getenv('WS_DEPTH_LEVEL', '5')),
            'ws_depth_interval': int(os.getenv('WS_DEPTH_INTERVAL', '500')),
            'obi_alpha': float(os.getenv('OBI_ALPHA', '0.6')),
            'obi_threshold': float(os.getenv('OBI_THRESHOLD', '0.18')),

            # Notifications
            'tg_bot_token': os.getenv('TG_BOT_TOKEN', ''),
            'tg_chat_id': os.getenv('TG_CHAT_ID', ''),

            # File Paths
            'kl_persist': os.getenv('KL_PERSIST', 'data/klines.csv'),
            'trades_path': os.getenv('TRADES_PATH', 'data/trades.csv'),
            'equity_path': os.getenv('EQUITY_PATH', 'data/equity.csv'),
            'results_path': os.getenv('RESULTS_PATH', 'data/results.csv'),
            'state_path': os.getenv('STATE_PATH', 'data/state.json'),
        }

        return cls(**env_mapping)


# Global config instance
_config: Optional[Config] = None


def load_config(env_file: Optional[str] = None) -> Config:
    """Load configuration from environment variables."""
    global _config
    _config = Config.from_env(env_file)
    return _config


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config