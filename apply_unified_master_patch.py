# apply_unified_master_patch.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import re, os, sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
def p(*xs): print(*xs)

def write_file(path: Path, text: str, backup_tag: str|None=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and backup_tag:
        bak = path.with_suffix(path.suffix + f".bak_{backup_tag}")
        if not bak.exists():
            bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(text, encoding="utf-8")

def patch_text(path: Path, replacers: list[tuple[re.Pattern,str]], backup_tag: str):
    if not path.exists():
        p(f"  ! Skip: {path} not found")
        return False
    src = path.read_text(encoding="utf-8")
    out = src
    changed = False
    for pat, repl in replacers:
        new = pat.sub(repl, out)
        if new != out:
            changed = True
            out = new
    if changed:
        write_file(path, out, backup_tag=backup_tag)
        p(f"  ✓ Patched {path}")
    else:
        p(f"  = No changes needed: {path.name}")
    return changed

def ensure_env_overrides():
    path = ROOT / "core" / "env_overrides.py"
    code = dedent(r"""
    # core/env_overrides.py
    # Мягкие .env-оверрайды и заполнение недостающих полей в конфиге.
    from __future__ import annotations
    import os
    from typing import Any

    def _get_bool(name: str, default: bool) -> bool:
        v = os.getenv(name, None)
        if v is None:
            return default
        return str(v).strip().lower() in {"1","true","yes","y","on"}

    def _get_float(name: str, default: float) -> float:
        v = os.getenv(name, None)
        try:
            return float(v) if v is not None else default
        except Exception:
            return default

    def _get_csv(name: str, default: list[str]) -> list[str]:
        v = os.getenv(name, "")
        if not v:
            return list(default or [])
        return [x.strip() for x in v.split(",") if x.strip()]

    def apply_env_overrides(cfg: Any) -> Any:
        """
        Аккуратно добавляет поля, если их нет в pydantic-конфиге/датаклассе.
        Ничего не ломает, только заполняет пропуски.
        """
        # базовые переключатели
        if not hasattr(cfg, "dry_run"):
            setattr(cfg, "dry_run", _get_bool("DRY_RUN", False))
        if not hasattr(cfg, "testnet"):
            setattr(cfg, "testnet", _get_bool("TESTNET", False))

        # торговые поля
        if not hasattr(cfg, "symbols"):
            setattr(cfg, "symbols", tuple(_get_csv("SYMBOLS", [])))
        if not hasattr(cfg, "timeframe"):
            setattr(cfg, "timeframe", os.getenv("TIMEFRAME", "1m"))

        # порог экстренного стопа с дефолтом 0.0
        if not hasattr(cfg, "min_account_balance"):
            setattr(cfg, "min_account_balance", _get_float("MIN_ACCOUNT_BALANCE_USDT", 0.0))

        # совместимость названий
        if hasattr(cfg, "risk_per_trade_pct"):
            pass
        elif hasattr(cfg, "RISK_PER_TRADE_PCT"):
            setattr(cfg, "risk_per_trade_pct", getattr(cfg, "RISK_PER_TRADE_PCT"))
        else:
            setattr(cfg, "risk_per_trade_pct", _get_float("RISK_PER_TRADE_PCT", 0.5))

        if hasattr(cfg, "max_daily_loss_pct"):
            pass
        elif hasattr(cfg, "MAX_DAILY_LOSS_PCT"):
            setattr(cfg, "max_daily_loss_pct", getattr(cfg, "MAX_DAILY_LOSS_PCT"))
        else:
            setattr(cfg, "max_daily_loss_pct", _get_float("MAX_DAILY_LOSS_PCT", 5.0))

        return cfg
    """).lstrip("\n")
    write_file(path, code, backup_tag="envovr_master")
    p(f"  ✓ Ensured {path}")

def ensure_utils_validate_symbol():
    path = ROOT / "core" / "utils.py"
    if not path.exists():
        p("  ! core/utils.py not found — skipping validate_symbol")
        return
    src = path.read_text(encoding="utf-8")
    if "def validate_symbol(" in src:
        p("  = validate_symbol() already exists")
        return
    add = dedent(r"""
    # --- compat helper for compat patches ---
    def validate_symbol(symbol: str) -> str:
        """
        Возвращает верхний регистр и не падает на странных типах.
        Совместимо с совместимостными патчами (compat).
        """
        try:
            s = str(symbol).strip().upper()
        except Exception:
            raise TypeError("symbol must be str-like")
        # Допускаем любые суффиксы; простая валидация на буквы/цифры
        if not s:
            raise ValueError("empty symbol")
        return s
    """).lstrip("\n")
    out = src.rstrip() + "\n\n" + add
    write_file(path, out, backup_tag="utils_master")
    p("  ✓ Added validate_symbol() into core/utils.py")

def patch_runner_live():
    path = ROOT / "runner" / "live.py"
    if not path.exists():
        p("  ! runner/live.py not found — skipping")
        return
    reps = [
        # 1) странный вызов self.getattr( ... ) → обычный getattr(
        (re.compile(r"\bself\.getattr\s*\("), "getattr("),
        # 2) getattr(config, 'min_account_balance' ...) → getattr(self.config, 'min_account_balance', 0.0)
        (re.compile(r"getattr\(\s*config\s*,\s*([\"'])min_account_balance\1\s*\)"),
         r'getattr(self.config, "min_account_balance", 0.0)'),
        # 3) если где-то остался getattr(self.config, "min_account_balance") без дефолта — добавим дефолт
        (re.compile(r"getattr\(\s*self\.config\s*,\s*([\"'])min_account_balance\1\s*\)"),
         r'getattr(self.config, "min_account_balance", 0.0)'),
    ]
    patch_text(path, reps, backup_tag="live_master")

def write_cli_integrated():
    path = ROOT / "cli_integrated.py"
    code = dedent(r"""
    # cli_integrated.py — надёжный CLI с .env и оверрайдами, без IndentationError
    from __future__ import annotations
    import os, sys, asyncio
    from typing import Optional
    import typer

    app = typer.Typer(name="trading-bot")

    # .env загрузка (мягкая)
    def _load_env(env_path: Optional[str]):
        if not env_path:
            return False
        try:
            from dotenv import load_dotenv
            if os.path.exists(env_path):
                load_dotenv(env_path, override=True)
                return True
        except Exception:
            pass
        # ручная загрузка .env без зависимостей
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line=line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k,v = line.split("=",1)
                        os.environ.setdefault(k.strip(), v.strip())
                return True
            except Exception:
                return False
        return False

    def _bool(v: Optional[str], default: bool=False)->bool:
        if v is None: return default
        return str(v).strip().lower() in {"1","true","t","yes","y","on"}

    def _csv(s: Optional[str])->list[str]:
        if not s: return []
        return [x.strip() for x in s.split(",") if x.strip()]

    def _build_config(mode: str):
        # стараемся использовать ваш pydantic-класс, но не падаем, если что
        cfg = None
        try:
            from core.config import Config
            cfg = Config(mode=mode)
        except Exception:
            from types import SimpleNamespace
            cfg = SimpleNamespace(mode=mode)
        # применим мягкие оверрайды (добавят недостающие поля)
        try:
            from core.env_overrides import apply_env_overrides
            cfg = apply_env_overrides(cfg)
        except Exception:
            pass
        return cfg

    def _print_banner(mode: str, cfg):
        try:
            from rich.console import Console
            from rich.table import Table
            console = Console()
            table = Table(title=f"{mode.capitalize()} Trading Mode", show_header=True, header_style="bold magenta")
            table.add_column("Setting", style="dim")
            table.add_column("Value")
            table.add_row("Mode", mode)
            table.add_row("Testnet", str(getattr(cfg, "testnet", False)))
            table.add_row("Dry Run", str(getattr(cfg, "dry_run", False)))
            syms = getattr(cfg, "symbols", [])
            if isinstance(syms, (list, tuple)): syms = ", ".join(syms)
            table.add_row("Symbols", str(syms or "-"))
            table.add_row("Timeframe", str(getattr(cfg, "timeframe", "1m")))
            table.add_row("Leverage", f"{getattr(cfg, 'leverage', 5)}x")
            table.add_row("Risk per Trade", f"{getattr(cfg, 'risk_per_trade_pct', 0.5)}%")
            table.add_row("Max Daily Loss", f"{getattr(cfg, 'max_daily_loss_pct', 5.0)}%")
            console.print(table)
        except Exception:
            # fallback принт
            print(f"Starting {mode.capitalize()} Trading Mode")
            print(f"  Testnet={getattr(cfg,'testnet',False)} DryRun={getattr(cfg,'dry_run',False)}")
            print(f"  Symbols={getattr(cfg,'symbols',[])} TF={getattr(cfg,'timeframe','1m')}")

    def _apply_cli_overrides(cfg, symbols: Optional[str], timeframe: Optional[str], testnet: bool, dry_run: bool):
        if symbols:
            setattr(cfg, "symbols", tuple(_csv(symbols)))
            os.environ["SYMBOLS"] = symbols
        if timeframe:
            setattr(cfg, "timeframe", timeframe)
            os.environ["TIMEFRAME"] = timeframe
        if testnet:
            setattr(cfg, "testnet", True)
            os.environ["TESTNET"] = "true"
        if dry_run:
            setattr(cfg, "dry_run", True)
            os.environ["DRY_RUN"] = "true"
        # всегда подтягиваем недостающие поля
        try:
            from core.env_overrides import apply_env_overrides
            apply_env_overrides(cfg)
        except Exception:
            pass
        return cfg

    @app.command("paper")
    def paper(
        config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to .env file"),
        symbols: Optional[str] = typer.Option(None, "--symbols", "-s", help="Comma separated, e.g. BTCUSDT,ETHUSDT"),
        timeframe: Optional[str] = typer.Option(None, "--timeframe", "-t"),
        testnet: bool = typer.Option(True, "--testnet/--no-testnet"),
        dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
        verbose: bool = typer.Option(False, "--verbose/--no-verbose"),
    ):
        if config:
            ok = _load_env(config)
            if ok:
                print(f"✅ CLI shim: using config {config}")
        cfg = _build_config("paper")
        _apply_cli_overrides(cfg, symbols, timeframe, testnet, dry_run)
        _print_banner("paper", cfg)
        try:
            from runner.paper import run_paper_trading
        except Exception as e:
            print(f"Import error: runner.paper.run_paper_trading not found: {e}")
            raise typer.Exit(code=1)
        asyncio.run(run_paper_trading(cfg))

    @app.command("live")
    def live(
        config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to .env file"),
        symbols: Optional[str] = typer.Option(None, "--symbols", "-s", help="Comma separated, e.g. BTCUSDT,ETHUSDT"),
        timeframe: Optional[str] = typer.Option(None, "--timeframe", "-t"),
        testnet: bool = typer.Option(False, "--testnet/--no-testnet"),
        dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run"),
        verbose: bool = typer.Option(False, "--verbose/--no-verbose"),
    ):
        if config:
            ok = _load_env(config)
            if ok:
                print(f"✅ CLI shim: using config {config}")
        cfg = _build_config("live")
        _apply_cli_overrides(cfg, symbols, timeframe, testnet, dry_run)
        _print_banner("live", cfg)

        # защита от случайного real live без dry_run/testnet
        if not getattr(cfg, "dry_run", False) and not getattr(cfg, "testnet", False):
            ans = input("Are you sure you want to trade with real money? [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print("Aborted.")
                raise typer.Exit(code=1)

        try:
            from runner.live import run_live_trading
        except Exception as e:
            print(f"Import error: runner.live.run_live_trading not found: {e}")
            raise typer.Exit(code=1)
        asyncio.run(run_live_trading(cfg))

    if __name__ == "__main__":
        app()
    """).lstrip("\n")
    write_file(path, code, backup_tag="cliint_master")
    p(f"  ✓ Rewrote {path} (safe CLI)")

def main():
    p("Applying unified master patch …")
    ensure_env_overrides()
    ensure_utils_validate_symbol()
    patch_runner_live()
    write_cli_integrated()
    p("Done.")

if __name__ == "__main__":
    main()
