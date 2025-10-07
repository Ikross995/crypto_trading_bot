#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stable CLI (rescue) for paper/live modes.
- Supports: --config, --symbols, --dry-run, --testnet, --timeframe, --verbose
- No fancy unicode, only ASCII to avoid SyntaxErrors.
"""

import os
import sys
from types import SimpleNamespace
from typing import Optional, List

try:
    import typer
except Exception:
    print("Missing 'typer'. Install: pip install typer[all]", file=sys.stderr)
    raise

app = typer.Typer(name="trading-bot", add_completion=False)

def _load_env_file(path: Optional[str]):
    data = {}
    if not path:
        return data
    if not os.path.exists(path):
        print(f"WARNING: env file not found: {path}")
        return data
    try:
        # Try python-dotenv first
        try:
            from dotenv import load_dotenv
            load_dotenv(path, override=True)
        except Exception:
            pass
        # Parse simple KEY=VAL lines as fallback
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)
                    data[k] = v
    except Exception as e:
        print(f"WARNING: failed to read env file {path}: {e}")
    return data

def _parse_symbols(val: Optional[str], fallback_env: dict) -> List[str]:
    if val:
        raw = val
    else:
        raw = os.getenv("SYMBOLS", fallback_env.get("SYMBOLS", ""))
    if not raw:
        return []
    parts = [x.strip().upper() for x in raw.replace(" ", "").split(",") if x.strip()]
    return parts

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name, str(default))
    return str(v).strip().lower() in {"1","true","t","yes","y","on"}

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default

def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, default)))
    except Exception:
        return default

def _build_config(mode: str,
                  config_file: Optional[str],
                  symbols_cli: Optional[str],
                  timeframe_cli: Optional[str],
                  testnet_flag: Optional[bool],
                  dry_run_flag: Optional[bool],
                  verbose: bool):
    env = _load_env_file(config_file)

    # Base values from env, with CLI overrides
    mode_val = mode
    testnet = bool(testnet_flag) if testnet_flag is not None else _bool_env("TESTNET", False)
    dry_run = bool(dry_run_flag) if dry_run_flag is not None else _bool_env("DRY_RUN", False)
    timeframe = timeframe_cli or os.getenv("TIMEFRAME", env.get("TIMEFRAME", "1m"))
    leverage = _int_env("LEVERAGE", 5)
    risk_per_trade_pct = _float_env("RISK_PER_TRADE_PCT", 0.5)
    max_daily_loss_pct = _float_env("MAX_DAILY_LOSS_PCT", 5.0)
    min_account_balance = _float_env("MIN_ACCOUNT_BALANCE", 0.0)

    symbols = _parse_symbols(symbols_cli, env)
    if not symbols:
        # Reasonable default to keep engine running
        symbols = ["BTCUSDT"]

    # Try to import pydantic Config if present, else SimpleNamespace
    cfg_kwargs = dict(
        mode=mode_val,
        dry_run=dry_run,
        testnet=testnet,
        timeframe=timeframe,
        symbols=symbols,
        leverage=leverage,
        risk_per_trade_pct=risk_per_trade_pct,
        max_daily_loss_pct=max_daily_loss_pct,
        min_account_balance=min_account_balance,
        save_reports=True,
    )
    # Optional API keys
    cfg_kwargs.update(dict(
        binance_api_key=os.getenv("BINANCE_API_KEY", env.get("BINANCE_API_KEY", "")),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", env.get("BINANCE_API_SECRET", "")),
    ))

    try:
        from core.config import Config  # type: ignore
        try:
            cfg = Config(**{k: v for k, v in cfg_kwargs.items() if k in (getattr(Config, "model_fields", {}) or getattr(Config, "__fields__", {}))})
            # ensure optional attrs
            for k, v in cfg_kwargs.items():
                if not hasattr(cfg, k):
                    try:
                        setattr(cfg, k, v)
                    except Exception:
                        pass
        except Exception:
            # Fallback to SimpleNamespace on mismatch
            cfg = SimpleNamespace(**cfg_kwargs)
    except Exception:
        cfg = SimpleNamespace(**cfg_kwargs)

    return cfg

def _print_cfg(cfg):
    try:
        syms = getattr(cfg, "symbols", [])
        syms_str = ", ".join(syms) if isinstance(syms, (list, tuple)) else str(syms)
        rows = [
            ("Mode", getattr(cfg, "mode", "")),
            ("Testnet", str(getattr(cfg, "testnet", False))),
            ("Dry Run", str(getattr(cfg, "dry_run", False))),
            ("Symbols", syms_str),
            ("Timeframe", getattr(cfg, "timeframe", "")),
            ("Leverage", f"{getattr(cfg, 'leverage', 0)}x"),
            ("Risk per Trade", f"{getattr(cfg, 'risk_per_trade_pct', 0.0)}%"),
            ("Max Daily Loss", f"{getattr(cfg, 'max_daily_loss_pct', 0.0)}%"),
        ]
        print(" Starting {} Trading Mode".format(str(getattr(cfg, "mode", "")).capitalize()))
        print(" Trading Bot Configuration")
        # simple ascii table
        width = max(len(k) for k, _ in rows) + 2
        print("┏" + "━"*(width+12) + "┓")
        print("┃ {:<{w}} ┃ {:<12} ┃".format("Setting", "Value", w=width))
        print("┡" + "━"*(width+12+2) + "┩")
        for k, v in rows:
            print("│ {:<{w}} │ {:<12} │".format(k, str(v), w=width))
        print("└" + "─"*(width+12+2) + "┘")
    except Exception:
        pass

@app.command("paper")
def paper(
    config: Optional[str] = typer.Option(None, "--config", help="Path to .env file"),
    symbols: Optional[str] = typer.Option(None, "--symbols", help="CSV symbols, e.g. BTCUSDT,ETHUSDT"),
    timeframe: Optional[str] = typer.Option(None, "--timeframe", help="Timeframe, e.g. 1m"),
    testnet: bool = typer.Option(True, "--testnet/--no-testnet", help="Use Binance Futures testnet"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Do not send real orders"),
    verbose: bool = typer.Option(True, "--verbose/--no-verbose"),
):
    cfg = _build_config("paper", config, symbols, timeframe, testnet, dry_run, verbose)
    _print_cfg(cfg)
    try:
        from runner.paper import run_paper_trading  # type: ignore
    except Exception as e:
        print(f"Import error (runner.paper): {e}", file=sys.stderr)
        raise
    import asyncio
    asyncio.run(run_paper_trading(cfg))

@app.command("live")
def live(
    config: Optional[str] = typer.Option(None, "--config", help="Path to .env file"),
    symbols: Optional[str] = typer.Option(None, "--symbols", help="CSV symbols, e.g. BTCUSDT,ETHUSDT"),
    timeframe: Optional[str] = typer.Option(None, "--timeframe", help="Timeframe, e.g. 1m"),
    testnet: bool = typer.Option(False, "--testnet/--no-testnet", help="Use Binance Futures testnet"),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run", help="Do not send real orders"),
    verbose: bool = typer.Option(True, "--verbose/--no-verbose"),
):
    cfg = _build_config("live", config, symbols, timeframe, testnet, dry_run, verbose)
    _print_cfg(cfg)

    if not cfg.testnet and not cfg.dry_run:
        ok = typer.confirm("Are you sure you want to trade with real money?", default=False)
        if not ok:
            raise typer.Abort()

    try:
        from runner.live import run_live_trading  # type: ignore
    except Exception as e:
        print(f"Import error (runner.live): {e}", file=sys.stderr)
        raise
    import asyncio
    asyncio.run(run_live_trading(cfg))

if __name__ == "__main__":
    app()
