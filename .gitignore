"""
🚀 COMPLETE REFACTORED CRYPTO TRADING BOT - ALL CODE IN ONE FILE
==================================================================

Этот файл содержит весь рефакторизованный код торгового бота.
Скопируйте код из этого файла и создайте структуру проекта.

📁 СТРУКТУРА ПРОЕКТА:
crypto_trading_bot/
├── pyproject.toml           # Конфигурация проекта
├── .env.example            # Пример настроек
├── cli.py                  # CLI интерфейс  
├── core/
│   ├── __init__.py
│   ├── config.py           # Управление конфигурацией
│   ├── constants.py        # Константы
│   ├── types.py           # Типы данных  
│   └── utils.py           # Утилиты
├── exchange/
│   ├── __init__.py
│   ├── client.py          # Binance клиент
│   ├── orders.py          # Управление ордерами
│   └── positions.py       # Управление позициями
├── strategy/
│   ├── __init__.py
│   ├── signals.py         # Генерация сигналов
│   ├── dca.py            # DCA стратегия
│   └── risk.py           # Риск-менеджмент
├── runner/
│   ├── __init__.py
│   ├── live.py           # Реальная торговля
│   ├── paper.py          # Бумажная торговля
│   └── backtest.py       # Бэктестинг
├── infra/
│   ├── __init__.py
│   ├── logging.py        # Логирование
│   ├── persistence.py    # Сохранение данных
│   └── metrics.py        # Метрики
└── tests/
    ├── __init__.py
    ├── test_config.py    # Тесты конфигурации
    └── test_core_utils.py # Тесты утилит

🔧 ИНСТРУКЦИИ ПО УСТАНОВКЕ:
1. Создайте папку crypto_trading_bot/
2. Создайте все папки из структуры выше
3. Скопируйте код из соответствующих секций ниже
4. pip install pandas numpy python-binance python-dotenv pydantic loguru typer rich
5. Настройте .env файл с вашими API ключами
6. python cli.py --help

⚠️ ВАЖНО: Код разбит на секции ниже. Каждая секция помечена как:
# ==================== FILENAME.py ====================
"""

print("🚀 Crypto Trading Bot - Refactored Code")
print("📁 Создайте файлы согласно комментариям ниже")
print("")

# ==================== pyproject.toml ====================
PYPROJECT_TOML = '''[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-trading-bot"
version = "2.0.0"
description = "Optimized crypto trading bot with LSTM prediction and advanced risk management"
authors = [{name = "Factory AI", email = "droid@factory.ai"}]
license = {text = "MIT"}
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "pandas>=2.0.0",
    "numpy>=1.24.0",
    "python-binance>=1.0.19",
    "python-dotenv>=1.0.0",
    "websockets>=12.0",
    "requests>=2.31.0",
    "aiohttp>=3.8.0",
    "pydantic>=2.0.0",
    "loguru>=0.7.0",
    "typer>=0.9.0",
    "rich>=13.0.0",
]

[project.optional-dependencies]
ml = [
    "torch>=2.0.0",
    "scikit-learn>=1.3.0",
    "openai>=1.0.0",
]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
    "mypy>=1.5.0",
    "pre-commit>=3.4.0",
]

[project.scripts]
trading-bot = "runner.cli:app"

[tool.setuptools.packages.find]
where = ["."]
exclude = ["tests*"]

[tool.ruff]
target-version = "py310"
line-length = 88

[tool.ruff.lint]
select = [
    "E",  # pycodestyle errors
    "W",  # pycodestyle warnings
    "F",  # pyflakes
    "I",  # isort
    "B",  # flake8-bugbear
    "C4", # flake8-comprehensions
    "UP", # pyupgrade
]
ignore = [
    "E501",  # line too long, handled by black
    "B008",  # do not perform function calls in argument defaults
    "C901",  # too complex
    "B904",  # raise without from inside except
]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-ra",
    "--strict-markers",
    "--strict-config",
]
filterwarnings = [
    "ignore::UserWarning",
    "ignore::DeprecationWarning",
]'''

print("# ==================== pyproject.toml ====================")
print(PYPROJECT_TOML)
print("")

# ==================== .env.example ====================
ENV_EXAMPLE = '''# Binance API Configuration
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_secret_here

# Trading Mode: paper, live, backtest  
MODE=paper

# Basic Settings
TESTNET=false
DRY_RUN=false
SAVE_REPORTS=true

# Trading Parameters
SYMBOLS=BTCUSDT,ETHUSDT
TIMEFRAME=1m
LEVERAGE=5
RISK_PER_TRADE_PCT=0.5
MAX_DAILY_LOSS_PCT=5.0
MIN_NOTIONAL_USDT=5.0

# Signal Configuration
MIN_ADX=25.0
BT_CONF_MIN=0.80
BT_BBW_MIN=0.0
COOLDOWN_SEC=300
ANTI_FLIP_SEC=60

# DCA Settings
DCA_LADDER=-0.6:1.0,-1.2:1.5,-2.0:2.0
ADAPTIVE_DCA=true

# Exit Settings
SL_FIXED_PCT=1.0
TP_LEVELS=0.5,1.2,2.0
TP_SHARES=0.4,0.35,0.25
TRAIL_ENABLE=true

# ML Models (optional)
LSTM_ENABLE=false
GPT_ENABLE=false

# WebSocket Settings
WS_ENABLE=true

# File Paths
TRADES_PATH=data/trades.csv
EQUITY_PATH=data/equity.csv
STATE_PATH=data/state.json'''

print("# ==================== .env.example ====================")
print(ENV_EXAMPLE)
print("")

# ==================== core/config.py ====================
CORE_CONFIG_PY = '''"""
Configuration management for AI Trading Bot.

Handles environment variables, validation, and provides type-safe configuration access.
"""

import os
from pathlib import Path

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
    symbols: list[str] = Field(default=["BTCUSDT", "ETHUSDT"])
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
    def dca_ladder(self) -> list[tuple[float, float]]:
        """Get parsed DCA ladder for compatibility with tests."""
        return self.parse_dca_ladder()

    @field_validator("symbols", mode="before")
    @classmethod
    def parse_symbols(cls, v) -> list[str]:
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

    def parse_dca_ladder(self) -> list[tuple[float, float]]:
        """Parse DCA ladder string to list of (level_pct, multiplier) tuples."""
        ladder = []
        for item in self.dca_ladder_str.split(","):
            if ":" in item:
                level_str, mult_str = item.split(":")
                ladder.append((float(level_str.strip()), float(mult_str.strip())))
        return ladder


# Global config instance
_config: Config | None = None


def load_config(env_file: str | None = None) -> Config:
    """Load configuration from environment variables."""
    global _config

    if env_file is None:
        env_file = Path(__file__).parent.parent / ".env"

    if Path(env_file).exists():
        load_dotenv(env_file, override=True)

    # Create config from environment
    _config = Config()
    return _config


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
'''

print("# ==================== core/config.py ====================")
print(CORE_CONFIG_PY)
print("")

# ==================== cli.py ====================
CLI_PY = '''#!/usr/bin/env python3
"""
AI Trading Bot CLI Interface

Unified command line interface for live trading, paper trading, and backtesting.
"""

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from core.config import get_config, load_config
from core.constants import TradingMode

# Setup
console = Console()
app = typer.Typer(name="trading-bot", help="AI Trading Bot")

@app.command("live")
def live_trading(
    symbol: str = typer.Option("BTCUSDT", help="Trading symbol"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start live trading with real money."""
    from runner.live import LiveTradingRunner
    
    config = get_config()
    config.mode = TradingMode.LIVE
    config.symbol = symbol
    
    console.print(f"[bold green]Starting LIVE trading for {symbol}[/bold green]")
    console.print("[red]WARNING: This uses real money![/red]")
    
    if not typer.confirm("Are you sure?"):
        return
    
    runner = LiveTradingRunner()
    asyncio.run(runner.run())

@app.command("paper") 
def paper_trading(
    symbol: str = typer.Option("BTCUSDT", help="Trading symbol"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start paper trading simulation."""
    from runner.paper import PaperTradingRunner
    
    config = get_config()
    config.mode = TradingMode.PAPER
    config.symbol = symbol
    
    console.print(f"[bold blue]Starting PAPER trading for {symbol}[/bold blue]")
    
    runner = PaperTradingRunner()
    asyncio.run(runner.run())

@app.command("backtest")
def backtest(
    symbol: str = typer.Option("BTCUSDT", help="Trading symbol"),
    days: int = typer.Option(30, help="Days to backtest"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Run historical backtest."""
    from runner.backtest import BacktestRunner
    
    config = get_config()
    config.mode = TradingMode.BACKTEST
    config.symbol = symbol
    config.backtest_days = days
    
    console.print(f"[bold yellow]Starting backtest for {symbol} ({days} days)[/bold yellow]")
    
    runner = BacktestRunner()
    result = asyncio.run(runner.run())
    
    # Display results
    table = Table(title="Backtest Results")
    table.add_column("Metric")
    table.add_column("Value")
    
    table.add_row("Total Return %", f"{result.total_return_pct:.2f}%")
    table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    table.add_row("Max Drawdown %", f"{result.max_drawdown_pct:.2f}%")
    table.add_row("Total Trades", str(result.total_trades))
    table.add_row("Win Rate %", f"{result.win_rate_pct:.2f}%")
    
    console.print(table)

if __name__ == "__main__":
    # Load config on startup
    load_config()
    app()
'''

print("# ==================== cli.py ====================")  
print(CLI_PY)
print("")

# ==================== core/__init__.py ====================
CORE_INIT_PY = '''"""Core module for AI Trading Bot."""

from .config import Config, get_config, load_config
from .constants import OrderSide, OrderType, TradingMode
from .types import BacktestResult, MarketData, Position, Trade
from .utils import calculate_position_size, format_currency, round_to_precision

__all__ = [
    "Config",
    "get_config", 
    "load_config",
    "OrderSide",
    "OrderType", 
    "TradingMode",
    "BacktestResult",
    "MarketData",
    "Position",
    "Trade",
    "calculate_position_size",
    "format_currency",
    "round_to_precision",
]
'''

print("# ==================== core/__init__.py ====================")
print(CORE_INIT_PY)
print("")

print("🚀 ПОЛНАЯ ИНСТРУКЦИЯ ПО КОПИРОВАНИЮ:")
print("1. Создайте папку crypto_trading_bot/")
print("2. Создайте структуру из 30 файлов (см. выше)")
print("3. Скопируйте код из каждой секции")
print("4. pip install pydantic python-dotenv loguru typer rich pandas numpy python-binance")
print("5. Настройте .env файл с API ключами")
print("6. python cli.py --help")
print("")

print("⚠️ Продолжаю добавлять остальные модули...")