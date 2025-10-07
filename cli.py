#!/usr/bin/env python3
"""
AI Trading Bot CLI Interface

Unified command line interface for live trading, paper trading, and backtesting.
Replaces the original monolithic script with clean, typed arguments.
"""

import asyncio
import logging
import sys
from pathlib import Path
import compat
compat.apply()
from infra.settings import load_profile, load_overrides, apply_settings_to_config
# --- POLYFILL: привести PositionManager / OrderManager к ожидаемому интерфейсу ---
import inspect, time
import compat
compat.apply()

try:
    from exchange.positions import PositionManager
except Exception:
    PositionManager = None

try:
    from exchange.orders import OrderManager
except Exception:
    OrderManager = None

def _pm_get_balance_from_client(client):
    for attr in ("get_account_balance", "get_balance", "balance"):
        if hasattr(client, attr):
            obj = getattr(client, attr)
            try:
                val = obj() if callable(obj) else obj
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, dict):
                    for k in ("available", "free", "balance"):
                        if k in val:
                            try:
                                return float(val[k])
                            except Exception:
                                pass
            except Exception:
                pass
    return 10000.0  # дефолт для mock

class _PMPosition:
    __slots__ = ("symbol","size","entry_price","side","leverage","unrealized_pnl","margin","timestamp")
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

def _ensure_pm_async_adapters():
    if PositionManager is None:
        return

    # внутреннее хранилище (если нет)
    if not hasattr(PositionManager, "_pm_storage_ready"):
        def _pm_storage_ready(self):
            if not hasattr(self, "_pm_positions"):
                self._pm_positions = {}
        PositionManager._pm_storage_ready = _pm_storage_ready

    # initialize()
    if not hasattr(PositionManager, "initialize"):
        async def initialize(self) -> None:
            self._pm_storage_ready()
            cfg = getattr(self, "config", None)
            symbols = []
            if cfg is not None:
                if getattr(cfg, "symbol", None):
                    symbols.append(cfg.symbol)
                if getattr(cfg, "symbols", None):
                    symbols.extend(cfg.symbols if isinstance(cfg.symbols, (list, tuple)) else [cfg.symbols])
            # вызовем setup_symbol, если он есть
            for sym in dict.fromkeys([s for s in symbols if s]):
                if hasattr(self, "setup_symbol"):
                    try:
                        self.setup_symbol(sym)
                    except Exception as e:
                        print(f"[PM.initialize] setup_symbol({sym}) failed: {e}")
        PositionManager.initialize = initialize

    # setup_symbol() — если нет, делаем no-op с попыткой настроить клиент
    if not hasattr(PositionManager, "setup_symbol"):
        def setup_symbol(self, symbol: str):
            client = getattr(self, "client", None)
            # плечо
            for fn in ("change_leverage", "set_leverage"):
                if hasattr(client, fn):
                    try:
                        getattr(client, fn)(symbol, getattr(self.config, "leverage", 1))
                    except Exception:
                        pass
            # тип маржи
            for fn in ("change_margin_type", "set_margin_type"):
                if hasattr(client, fn):
                    try:
                        getattr(client, fn)(symbol, "ISOLATED")
                    except Exception:
                        pass
            # режим позиций
            for fn in ("change_position_mode", "set_position_mode"):
                if hasattr(client, fn):
                    try:
                        getattr(client, fn)(True)
                    except Exception:
                        pass
            self._pm_storage_ready()
            if symbol not in self._pm_positions:
                self._pm_positions[symbol] = _PMPosition(symbol)
        PositionManager.setup_symbol = setup_symbol

    # get_position()
    if not hasattr(PositionManager, "get_position"):
        def get_position(self, symbol: str, force_refresh: bool=False):
            self._pm_storage_ready()
            pos = self._pm_positions.get(symbol)
            if pos is None:
                pos = _PMPosition(symbol)
                self._pm_positions[symbol] = pos
            return pos
        PositionManager.get_position = get_position

    # get_all_positions()
    if not hasattr(PositionManager, "get_all_positions"):
        def get_all_positions(self):
            self._pm_storage_ready()
            return list(self._pm_positions.values())
        PositionManager.get_all_positions = get_all_positions

    # get_account_balance()
    if not hasattr(PositionManager, "get_account_balance"):
        def get_account_balance(self):
            client = getattr(self, "client", None)
            return float(_pm_get_balance_from_client(client) if client is not None else 10000.0)
        PositionManager.get_account_balance = get_account_balance

    # get_position_risk_metrics()
    if not hasattr(PositionManager, "get_position_risk_metrics"):
        def get_position_risk_metrics(self, symbol: str):
            p = self.get_position(symbol)
            return {
                "symbol": symbol,
                "size": getattr(p, "size", 0.0),
                "entry_price": getattr(p, "entry_price", 0.0),
                "leverage": getattr(p, "leverage", getattr(self.config, "leverage", None)),
                "unrealized_pnl": getattr(p, "unrealized_pnl", 0.0),
                "margin": getattr(p, "margin", 0.0),
            }
        PositionManager.get_position_risk_metrics = get_position_risk_metrics

    # calculate_position_size()
    if not hasattr(PositionManager, "calculate_position_size"):
        def calculate_position_size(self, symbol: str, entry_price: float, stop_price: float):
            bal = self.get_account_balance()
            risk_pct = float(getattr(self.config, "risk_per_trade", 0.005))  # 0.5% по умолчанию
            risk_amount = bal * risk_pct
            stop_dist = abs(float(entry_price) - float(stop_price))
            if stop_dist <= 0:
                return 0.0
            qty = risk_amount / stop_dist
            return max(qty, 0.0)
        PositionManager.calculate_position_size = calculate_position_size

    # clear_cache()
    if not hasattr(PositionManager, "clear_cache"):
        def clear_cache(self):
            if hasattr(self, "_pm_positions"):
                self._pm_positions.clear()
        PositionManager.clear_cache = clear_cache

    # --- async-адаптеры, которые ожидают движки ---
    if not hasattr(PositionManager, "get_positions") or not inspect.iscoroutinefunction(getattr(PositionManager, "get_positions")):
        async def get_positions(self):
            cfg = getattr(self, "config", None)
            syms = []
            if cfg is not None:
                if getattr(cfg, "symbol", None):
                    syms.append(cfg.symbol)
                if getattr(cfg, "symbols", None):
                    syms.extend(cfg.symbols if isinstance(cfg.symbols, (list, tuple)) else [cfg.symbols])
            return [self.get_position(s) for s in dict.fromkeys([s for s in syms if s])]
        PositionManager.get_positions = get_positions

    if not hasattr(PositionManager, "update_position"):
        async def update_position(self, position):
            sym = getattr(position, "symbol", None) or (position.get("symbol") if isinstance(position, dict) else None)
            return self.get_position(sym) if sym else position
        PositionManager.update_position = update_position

    if not hasattr(PositionManager, "handle_filled_order"):
        async def handle_filled_order(self, order):
            sym = getattr(order, "symbol", None) or (order.get("symbol") if isinstance(order, dict) else None)
            if sym:
                self.get_position(sym)  # «обновим»
        PositionManager.handle_filled_order = handle_filled_order

    if not hasattr(PositionManager, "sync_positions") or not inspect.iscoroutinefunction(getattr(PositionManager, "sync_positions")):
        async def sync_positions(self):
            for p in await self.get_positions():
                sym = getattr(p, "symbol", None)
                if sym:
                    self._pm_positions[sym] = p
        PositionManager.sync_positions = sync_positions

def _ensure_om_async_adapters():
    if OrderManager is None:
        return
    if not hasattr(OrderManager, "create_order_async"):
        async def create_order_async(self, *args, **kwargs):
            return self.create_order(*args, **kwargs)
        OrderManager.create_order_async = create_order_async
    if not hasattr(OrderManager, "cancel_order_async"):
        async def cancel_order_async(self, *args, **kwargs):
            return self.cancel_order(*args, **kwargs)
        OrderManager.cancel_order_async = cancel_order_async
# --- /POLYFILL ---

try:
    from exchange.positions import PositionManager
except Exception:
    PositionManager = None

def _ensure_pm_async_adapters():
    if PositionManager is None:
        return

    # initialize()
    if not hasattr(PositionManager, "initialize"):
        async def initialize(self) -> None:
            cfg = getattr(self, "config", None)
            syms = []
            if cfg is not None:
                if getattr(cfg, "symbol", None):
                    syms.append(cfg.symbol)
                if getattr(cfg, "symbols", None):
                    syms.extend(cfg.symbols if isinstance(cfg.symbols, (list, tuple)) else [cfg.symbols])

            # уникальные, по порядку
            ordered, seen = [], set()
            for s in syms:
                if s and s not in seen:
                    ordered.append(s); seen.add(s)

            for sym in ordered:
                try:
                    self.setup_symbol(sym)
                except Exception as e:
                    print(f"[PM.initialize] setup_symbol({sym}) failed: {e}")
        PositionManager.initialize = initialize

    # get_positions()
    if not hasattr(PositionManager, "get_positions") or not inspect.iscoroutinefunction(getattr(PositionManager, "get_positions")):
        async def get_positions(self):
            cfg = getattr(self, "config", None)
            syms = []
            if cfg is not None:
                if getattr(cfg, "symbol", None):
                    syms.append(cfg.symbol)
                if getattr(cfg, "symbols", None):
                    syms.extend(cfg.symbols if isinstance(cfg.symbols, (list, tuple)) else [cfg.symbols])

            ordered, seen = [], set()
            for s in syms:
                if s and s not in seen:
                    ordered.append(s); seen.add(s)

            out = []
            for s in ordered:
                try:
                    pos = self.get_position(s, force_refresh=True)
                except TypeError:
                    pos = self.get_position(s)
                if pos is not None:
                    out.append(pos)
            return out
        PositionManager.get_positions = get_positions

    # update_position()
    if not hasattr(PositionManager, "update_position"):
        async def update_position(self, position):
            sym = getattr(position, "symbol", None) or (position.get("symbol") if isinstance(position, dict) else None)
            if not sym:
                return position
            try:
                return self.get_position(sym, force_refresh=True)
            except TypeError:
                return self.get_position(sym)
        PositionManager.update_position = update_position

    # handle_filled_order()
    if not hasattr(PositionManager, "handle_filled_order"):
        async def handle_filled_order(self, order):
            sym = getattr(order, "symbol", None) or (order.get("symbol") if isinstance(order, dict) else None)
            if sym:
                try:
                    self.get_position(sym, force_refresh=True)
                except TypeError:
                    self.get_position(sym)
        PositionManager.handle_filled_order = handle_filled_order

    # sync_positions()
    if not hasattr(PositionManager, "sync_positions") or not inspect.iscoroutinefunction(getattr(PositionManager, "sync_positions")):
        async def sync_positions(self):
            for p in await self.get_positions():
                sym = getattr(p, "symbol", None)
                if sym:
                    self._positions_cache[sym] = p
        PositionManager.sync_positions = sync_positions
# --- /POLYFILL ---

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
from core.types import BacktestResult

# Setup rich console
console = Console()
app = typer.Typer(
    name="trading-bot",
    help="AI Trading Bot with LSTM prediction and advanced risk management",
    add_completion=False,
)

# Global state for clean shutdown
_shutdown_requested = False


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
        except ValueError as e:
            console.print(f"[red]Invalid symbol {symbol}: {e}[/red]")
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
    table.add_row("Max Daily Loss", f"{config.max_daily_loss_pct}%")

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
    config_file: str | None = typer.Option(
        None, "--config", help="Config file path"
    ),
) -> None:
    """
    Run live trading mode.

    Connects to Binance and executes real trades based on signals.
    Use --testnet for safe testing with testnet funds.
    """
    setup_logging(verbose)

    # Load configuration
    config = load_config(config_file)
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
        # Import and run live trading
        from runner.live import run_live_trading
        _ensure_pm_async_adapters()
        asyncio.run(run_live_trading(config))

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested. Cleaning up...[/yellow]")
    except Exception as e:
        console.print(f"[red]Live trading failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def paper(
    symbols: list[str] | None = typer.Option(
        None, "--symbols", "-s", help="Trading symbols"
    ),
    timeframe: str | None = typer.Option(
        None, "--timeframe", "-t", help="Timeframe"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="Config file path"
    ),
) -> None:
    """
    Run paper trading mode.

    Simulates trading with real market data but fake money.
    Perfect for testing strategies without risk.
    """
    setup_logging(verbose)

    # Load configuration
    config = load_config(config_file)
    config.mode = TradingMode.PAPER
    config.dry_run = True

    if symbols:
        config.symbols = validate_symbols(symbols)
    if timeframe:
        config.timeframe = timeframe

    console.print("[blue]Starting Paper Trading Mode[/blue]")
    print_config_summary()

    try:
        # Import and run paper trading
        from runner.paper import run_paper_trading
        _ensure_pm_async_adapters()
        _ensure_om_async_adapters()
        asyncio.run(run_paper_trading(config))

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested.[/yellow]")
    except Exception as e:
        console.print(f"[red]Paper trading failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def backtest(
    symbol: str = typer.Option("BTCUSDT", "--symbol", "-s", help="Symbol to backtest"),
    timeframe: str = typer.Option("1m", "--timeframe", "-t", help="Timeframe"),
    days: int = typer.Option(90, "--days", "-d", help="Days of historical data"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
    save_report: bool = typer.Option(
        True, "--save-report", help="Save detailed report"
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="Config file path"
    ),
) -> None:
    """
    Run backtesting on historical data.

    Tests the trading strategy on past market data to evaluate performance.
    """
    setup_logging(verbose)

    # Load configuration
    config = load_config(config_file)
    config.mode = TradingMode.BACKTEST
    config.symbol = symbol
    config.timeframe = timeframe
    config.backtest_days = days
    config.save_reports = save_report

    try:
        validate_symbols([symbol])
    except Exception:
        raise typer.Exit(1)

    console.print(
        f"[magenta]Starting Backtest: {symbol} {timeframe} ({days} days)[/magenta]"
    )

    try:
        # Import and run backtesting
        from runner.backtest import BacktestRunner

        runner = BacktestRunner(config)

        with console.status(f"Running backtest for {symbol}..."):
            result = runner.run_backtest(symbol, days)

        # Display results
        print_backtest_results(result)

        if save_report:
            report_path = f"backtest_report_{symbol}_{timeframe}_{days}d.md"
            runner.save_report(result, report_path)
            console.print(f"[green]Report saved to {report_path}[/green]")

    except Exception as e:
        console.print(f"[red]Backtest failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def portfolio(
    symbols: list[str] = typer.Option(
        ["BTCUSDT", "ETHUSDT"], "--symbols", "-s", help="Portfolio symbols"
    ),
    timeframe: str = typer.Option("1m", "--timeframe", "-t", help="Timeframe"),
    days: int = typer.Option(90, "--days", "-d", help="Days of historical data"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
    config_file: str | None = typer.Option(
        None, "--config", help="Config file path"
    ),
) -> None:
    """
    Run portfolio backtest across multiple symbols.

    Evaluates the strategy performance across a portfolio of symbols.
    """
    setup_logging(verbose)

    config = load_config(config_file)
    config.mode = TradingMode.BACKTEST
    config.timeframe = timeframe
    config.backtest_days = days

    symbols = validate_symbols(symbols)

    console.print(
        f"[magenta]Starting Portfolio Backtest: {', '.join(symbols)} ({days} days)[/magenta]"
    )

    try:
        from runner.backtest import BacktestRunner

        runner = BacktestRunner(config)

        results = []
        for symbol in track(symbols, description="Running backtests..."):
            result = runner.run_backtest(symbol, days)
            results.append(result)

        # Print portfolio summary
        print_portfolio_results(results)

    except Exception as e:
        console.print(f"[red]Portfolio backtest failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def optimize(
    symbol: str = typer.Option("BTCUSDT", "--symbol", "-s", help="Symbol to optimize"),
    timeframe: str = typer.Option("1m", "--timeframe", "-t", help="Timeframe"),
    days: int = typer.Option(90, "--days", "-d", help="Days of data for optimization"),
    trials: int = typer.Option(100, "--trials", help="Number of optimization trials"),
    metric: str = typer.Option(
        "sharpe", "--metric", help="Optimization metric (sharpe, return, drawdown)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
) -> None:
    """
    Optimize strategy parameters using historical data.

    Finds the best parameter combination for maximum performance.
    """
    setup_logging(verbose)

    console.print(
        f"[yellow]Starting Parameter Optimization: {symbol} ({trials} trials)[/yellow]"
    )

    try:
        from runner.optimizer import ParameterOptimizer

        config = load_config()
        optimizer = ParameterOptimizer(config)

        best_params = optimizer.optimize(symbol, timeframe, days, trials, metric)

        # Display results
        table = Table(title="Best Parameters Found")
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", style="green")

        for param, value in best_params.items():
            table.add_row(param, str(value))

        console.print(table)

    except Exception as e:
        console.print(f"[red]Optimization failed: {e}[/red]")
        raise typer.Exit(1)


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
                console.print("[green]Configuration is valid![/green]")

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
        import shutil

        shutil.copy(env_example, env_file)
        console.print(f"[green]Created {env_file} from template[/green]")
        console.print("[yellow]Please edit the file with your API credentials[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to create .env file: {e}[/red]")


def print_backtest_results(result: BacktestResult) -> None:
    """Print backtest results in a nice table."""
    table = Table(title=f"Backtest Results: {result.symbol}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Return", f"{result.total_return:.2%}")
    table.add_row("CAGR", f"{result.total_return:.2%}")  # Simplified
    table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    table.add_row("Max Drawdown", f"{result.max_drawdown:.2%}")
    table.add_row("Total Trades", str(result.total_trades))
    table.add_row("Win Rate", f"{result.win_rate:.2%}")
    table.add_row("Profit Factor", f"{result.profit_factor:.2f}")
    table.add_row("Expectancy", f"${result.expectancy:.2f}")

    console.print(table)


def print_portfolio_results(results: list[BacktestResult]) -> None:
    """Print portfolio backtest results."""
    table = Table(title="Portfolio Backtest Results")
    table.add_column("Symbol", style="cyan")
    table.add_column("Return", style="green")
    table.add_column("Sharpe", style="blue")
    table.add_column("Max DD", style="red")
    table.add_column("Trades", style="magenta")
    table.add_column("Win Rate", style="yellow")

    total_return = 0.0
    total_trades = 0

    for result in results:
        table.add_row(
            result.symbol,
            f"{result.total_return:.2%}",
            f"{result.sharpe_ratio:.2f}",
            f"{result.max_drawdown:.2%}",
            str(result.total_trades),
            f"{result.win_rate:.2%}",
        )
        total_return += result.total_return
        total_trades += result.total_trades

    # Add summary row
    avg_return = total_return / len(results) if results else 0
    table.add_row(
        "[bold]AVERAGE[/bold]",
        f"[bold]{avg_return:.2%}[/bold]",
        "",
        "",
        f"[bold]{total_trades}[/bold]",
        "",
    )

    console.print(table)


if __name__ == "__main__":
    app()
