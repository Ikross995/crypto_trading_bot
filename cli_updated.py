# --- IMBA: apply env overrides for TESTNET/DRY_RUN (rescue, idempotent) ---
import os as _imba_os

def _imba_env_bool(name: str):
    v = _imba_os.getenv(name, None)
    if v is None: return None
    return str(v).strip().lower() in {"1","true","t","yes","y","on"}

def _imba_apply_env_overrides(cfg):
    try:
        et = _imba_env_bool("TESTNET")
        ed = _imba_env_bool("DRY_RUN")
        if et is not None:
            cfg.testnet = bool(et)
        if ed is not None:
            cfg.dry_run = bool(ed)
    except Exception:
        pass
# --- /IMBA helper ---

#!/usr/bin/env python3
"""
AI Trading Bot CLI Interface - UPDATED WITH LATEST FIXES

Unified command line interface for live trading, paper trading, and backtesting.
Includes all latest fixes for PositionManager, MetricsCollector, and BinanceClient.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Import fixes first
try:
    # Apply compatibility patches
    import compat
    compat.apply()
except ImportError:
    print("Warning: compat module not found, proceeding without patches")

try:
    import typer
    from rich.console import Console
    from rich.progress import track
    from rich.table import Table
except ImportError:
    print("Missing dependencies. Install with: pip install typer rich")
    sys.exit(1)

from core.config import get_config, load_config
from core.constants import TradingMode

# Setup rich console
console = Console()
app = typer.Typer(
    name="trading-bot",
    help="AI Trading Bot with LSTM prediction and advanced risk management",
    add_completion=False,
)


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("trading_bot.log"),
        ],
    )

    # Reduce noise from external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def validate_symbols(symbols: list[str]) -> list[str]:
    """Validate and normalize trading symbols."""
    from core.utils import normalize_symbol

    # Handle comma-separated symbols in a single string
    all_symbols = []
    for symbol_str in symbols:
        if ',' in symbol_str:
            all_symbols.extend([s.strip() for s in symbol_str.split(',') if s.strip()])
        else:
            all_symbols.append(symbol_str.strip())

    validated = []
    for symbol in all_symbols:
        try:
            normalized = normalize_symbol(symbol)
            validated.append(normalized)
        except (ValueError, AttributeError):
            # Fallback validation
            if len(symbol) >= 6 and symbol.isupper():
                validated.append(symbol)
            else:
                console.print(f"[red]Invalid symbol {symbol}[/red]")
                continue

    if not validated:
        console.print("[red]No valid symbols provided![/red]")
        raise typer.Exit(1)

    return validated


def print_config_summary() -> None:
    """Print configuration summary."""
    config = get_config()

    table = Table(title="Trading Bot Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Mode", config.mode.value)
    table.add_row("Testnet", str(config.testnet))
    table.add_row("Dry Run", str(config.dry_run))
    table.add_row("Symbols", ", ".join(config.symbols))
    table.add_row("Timeframe", config.timeframe)
    table.add_row("Leverage", f"{config.leverage}x")
    table.add_row("Risk per Trade", f"{config.risk_per_trade_pct}%")
    
    # Use our fixed property
    table.add_row("Max Daily Loss", f"{config.max_daily_loss}%")

    console.print(table)


@app.command()
def live(
    symbols: list[str] | None = typer.Option(
        None, "--symbols", "-s", help="Trading symbols (e.g. BTCUSDT)"
    ),
    timeframe: str | None = typer.Option(
        None, "--timeframe", "-t", help="Timeframe (e.g. 1m, 5m, 1h)"
    ),
    testnet: bool = typer.Option(
        False, "--testnet", help="Use testnet instead of mainnet"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Simulate trades without real orders"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),

) -> None:
    """
    Run live trading mode.

    Connects to Binance and executes real trades based on signals.
    Use --testnet for safe testing with testnet funds.
    """
    setup_logging(verbose)

    # Load configuration
    config = load_config(None)
    config.mode = TradingMode.LIVE
    config.dry_run = dry_run
    config.testnet = testnet

    if symbols:
        config.symbols = validate_symbols(symbols)
    if timeframe:
        config.timeframe = timeframe

    console.print("[green]Starting Live Trading Mode[/green]")
    print_config_summary()

    if not config.has_api_credentials():
        console.print("[red]ERROR: Missing API credentials![/red]")
        console.print("Set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")
        raise typer.Exit(1)

    if not testnet and not typer.confirm(
        "Are you sure you want to trade with real money?"
    ):
        console.print("Aborted.")
        raise typer.Exit()

    try:
        # Import and run live trading with our fixes
        from runner.live import run_live_trading
        asyncio.run(run_live_trading(config))

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested. Cleaning up...[/yellow]")
    except Exception as e:
        console.print(f"[red]Live trading failed: {e}[/red]")
        logging.exception("Live trading error")
        raise typer.Exit(1)


@app.command()
def paper(
    symbols: list[str] | None = typer.Option(
        None, "--symbols", "-s", help="Trading symbols"
    ),
    timeframe: str | None = typer.Option(
        None, "--timeframe", "-t", help="Timeframe"
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Configuration file path (e.g., .env.testnet)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
) -> None:
    """
    Run paper trading mode.

    Simulates trading with real market data but fake money.
    Perfect for testing strategies without risk.
    """
    # Load configuration with --config parameter support BEFORE logging setup
    if config:
        print(f"Loading configuration from: {config}")
        try:
            from core.config_loader import load_config_file
            load_config_file(config)
        except ImportError:
            print(f"Warning: config_loader not found, loading {config} manually")
            try:
                from dotenv import load_dotenv
                load_dotenv(config, override=True)
                print(f"✅ Loaded {config}")
            except ImportError:
                print("ERROR: python-dotenv not installed, cannot load config file")
    
    setup_logging(verbose)

    # Load configuration
    config = load_config(None)
    config.mode = TradingMode.PAPER
    config.dry_run = True

    if symbols:
        config.symbols = validate_symbols(symbols)
    if timeframe:
        config.timeframe = timeframe

    console.print("[blue]Starting Paper Trading Mode[/blue]")
    print_config_summary()

    try:
        # Import and run paper trading with our fixes
        from runner.paper import run_paper_trading
        asyncio.run(run_paper_trading(config))

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested.[/yellow]")
    except Exception as e:
        console.print(f"[red]Paper trading failed: {e}[/red]")
        logging.exception("Paper trading error")
        raise typer.Exit(1)


@app.command()
def test(
    component: str = typer.Option("all", help="Component to test (all, imports, startup, positions)")
) -> None:
    """
    Run tests to verify bot functionality.
    """
    console.print(f"[yellow]Testing {component}...[/yellow]")
    
    if component == "imports" or component == "all":
        console.print("\n🧪 Testing imports...")
        try:
            # Test our fixed imports
            from core.constants import SignalType, PositionSide, TradingMode
            from core.config import Config, get_config
            from exchange.positions import PositionManager
            from infra.metrics import MetricsCollector
            
            console.print("✅ Core imports successful")
            
            # Test config properties
            config = get_config()
            console.print(f"✅ max_daily_loss: {config.max_daily_loss}")
            console.print(f"✅ close_positions_on_exit: {config.close_positions_on_exit}")
            
            # Test metrics collector
            metrics = MetricsCollector(config)
            console.print(f"✅ consecutive_errors: {metrics.consecutive_errors}")
            
            console.print("🎉 All import tests passed!")
            
        except Exception as e:
            console.print(f"[red]Import test failed: {e}[/red]")
            
    if component == "startup" or component == "all":
        console.print("\n🧪 Testing startup...")
        try:
            from exchange.positions import PositionManager
            from infra.metrics import MetricsCollector
            
            config = get_config()
            
            # Test PositionManager
            pm = PositionManager(config)
            asyncio.run(pm.initialize())
            console.print("✅ PositionManager initialization")
            
            # Test MetricsCollector  
            metrics = MetricsCollector(config)
            metrics.start()
            console.print("✅ MetricsCollector startup")
            
            console.print("🎉 All startup tests passed!")
            
        except Exception as e:
            console.print(f"[red]Startup test failed: {e}[/red]")


@app.command()
def fix(
    clean_cache: bool = typer.Option(True, help="Clean Python cache files"),
    validate: bool = typer.Option(True, help="Validate configuration")
) -> None:
    """
    Fix common issues with the trading bot.
    """
    console.print("[yellow]Running bot fixes...[/yellow]")
    
    if clean_cache:
        console.print("\n🧹 Cleaning Python cache...")
        import shutil
        import os
        
        cleaned = 0
        for root, dirs, files in os.walk('.'):
            for dir_name in dirs[:]:
                if dir_name == '__pycache__':
                    cache_dir = os.path.join(root, dir_name)
                    shutil.rmtree(cache_dir)
                    dirs.remove(dir_name)
                    cleaned += 1
        
        console.print(f"✅ Cleaned {cleaned} cache directories")
    
    if validate:
        console.print("\n🔍 Validating configuration...")
        try:
            config = get_config()
            console.print(f"✅ Config loaded successfully")
            console.print(f"✅ Symbols: {config.symbols}")
            console.print(f"✅ API credentials: {'✅ Set' if config.has_api_credentials() else '❌ Missing'}")
        except Exception as e:
            console.print(f"[red]Config validation failed: {e}[/red]")
    
    console.print("\n🎉 Fix completed!")


@app.command()  
def config(
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
    validate: bool = typer.Option(False, "--validate", help="Validate configuration"),
    create_env: bool = typer.Option(
        False, "--create-env", help="Create example .env file"
    ),
) -> None:
    """
    Configuration management utilities.
    """
    if create_env:
        create_example_env()
        return

    if show or validate:
        try:
            load_config()

            if show:
                print_config_summary()

            if validate:
                config = get_config()
                console.print("[green]Configuration is valid![/green]")
                
                # Test our fixed properties
                console.print(f"✅ max_daily_loss property: {config.max_daily_loss}")
                console.print(f"✅ close_positions_on_exit property: {config.close_positions_on_exit}")

        except Exception as e:
            console.print(f"[red]Configuration error: {e}[/red]")
            raise typer.Exit(1)
    else:
        console.print("Use --show, --validate, or --create-env")


def create_example_env() -> None:
    """Create example .env file."""
    env_example = Path(".env.example") 
    env_file = Path(".env")

    if env_file.exists():
        if not typer.confirm(f"{env_file} already exists. Overwrite?"):
            return

    try:
        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
        else:
            # Create basic .env if example doesn't exist
            with open(env_file, 'w') as f:
                f.write("""# Binance API Configuration
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_secret_here

# Trading Mode: paper, live, backtest  
MODE=paper

# Basic Settings
TESTNET=true
DRY_RUN=true
SAVE_REPORTS=true

# Trading Parameters
SYMBOLS=BTCUSDT,ETHUSDT
TIMEFRAME=1m
LEVERAGE=5
RISK_PER_TRADE_PCT=0.5
MAX_DAILY_LOSS_PCT=5.0
""")
        console.print(f"[green]Created {env_file} from template[/green]")
        console.print("[yellow]Please edit the file with your API credentials[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to create .env file: {e}[/red]")


if __name__ == "__main__":
    # Load config on startup
    try:
        load_config()
    except Exception as e:
        console.print(f"[red]Failed to load config: {e}[/red]")
        console.print("Run: python cli_updated.py fix")
        sys.exit(1)
    
    app()