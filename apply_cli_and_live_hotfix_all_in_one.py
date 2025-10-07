# -*- coding: utf-8 -*-
"""
Единый хотфикс:
- Переписывает cli_integrated.py на стабильную версию (Typer, .env, live/paper).
- Чинит runner/live.py: убирает 'self.getattr', добавляет безопасный getattr(self.config, 'min_account_balance', 0.0).
Запуск: python apply_cli_and_live_hotfix_all_in_one.py
"""

from __future__ import annotations
import os, re, sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent

def backup(path: Path):
    if path.exists():
        bk = path.with_suffix(path.suffix + ".bak_unified")
        try:
            bk.write_bytes(path.read_bytes())
            print(f"📦 Backup: {path.relative_to(ROOT)} -> {bk.name}")
        except Exception as e:
            print(f"⚠️  Backup failed for {path}: {e}")

def write_cli_integrated():
    """Полная замена cli_integrated.py корректной реализацией."""
    target = ROOT / "cli_integrated.py"
    backup(target)

    code = dedent(r"""
    # -*- coding: utf-8 -*-
    from __future__ import annotations

    import os
    import sys
    import asyncio
    from pathlib import Path
    from typing import List, Optional

    try:
        import typer
    except Exception:
        raise SystemExit("typer not installed. Run: pip install typer[all] rich python-dotenv")

    from rich.console import Console
    from rich.table import Table

    # --- dotenv (не обязателен; если нет — fallback парсер .env) ---
    try:
        from dotenv import load_dotenv
        DOTENV_OK = True
    except Exception:
        DOTENV_OK = False

    console = Console()
    app = typer.Typer(help="Integrated Trading CLI (live/paper).")

    # -------- helpers --------
    def _bool_env(name: str, default: bool=False) -> bool:
        v = os.getenv(name, str(default))
        return str(v).strip().lower() in {"1","true","t","yes","y","on"}

    def _float_env(name: str, default: float=0.0) -> float:
        try:
            return float(str(os.getenv(name, default)))
        except Exception:
            return default

    def _int_env(name: str, default: int=0) -> int:
        try:
            return int(float(str(os.getenv(name, default))))
        except Exception:
            return default

    def _load_env_file(env_path: Optional[str]):
        """Поддержка --config .env.*. Если dotenv нет — прочитаем вручную простые 'KEY=VAL'."""
        if not env_path:
            return
        p = Path(env_path)
        if not p.exists():
            console.print(f"[yellow]Warning: {env_path} not found, continuing with process env[/]")
            return
        if DOTENV_OK:
            load_dotenv(str(p), override=True)
            console.print(f"[green]✅ Loaded {p.name}[/]")
        else:
            # простой разбор
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
                console.print(f"[green]✅ Loaded {p.name} (manual parser)[/]")
            except Exception as e:
                console.print(f"[yellow]Warning: failed to parse {p.name}: {e}[/]")

    def _print_config_table(mode: str, symbols: List[str], timeframe: str, leverage: int,
                            risk_pct: float, max_daily_loss: float, testnet: bool, dry_run: bool):
        table = Table(title="Trading Bot Configuration")
        table.add_column("Setting", style="cyan", no_wrap=True)
        table.add_column("Value", style="magenta")

        table.add_row("Mode", mode)
        table.add_row("Testnet", str(testnet))
        table.add_row("Dry Run", str(dry_run))
        table.add_row("Symbols", ", ".join(symbols))
        table.add_row("Timeframe", timeframe)
        table.add_row("Leverage", f"{leverage}x")
        table.add_row("Risk per Trade", f"{risk_pct}%")
        table.add_row("Max Daily Loss", f"{max_daily_loss}%")
        console.print(table)

    # --- загрузка/создание Config ---
    def _build_config(mode: str, symbols: List[str], timeframe: Optional[str],
                      testnet: bool, dry_run: bool) -> "object":
        """
        Пытаемся использовать core.config.Config; при отсутствии — создаём минимальный fallback-объект.
        Гарантируем поле min_account_balance (по умолчанию 0.0).
        """
        # значения по умолчанию/из env
        tf = timeframe or os.getenv("TIMEFRAME", "1m")
        lev = _int_env("LEVERAGE", 5)
        risk_pct = _float_env("RISK_PER_TRADE_PCT", 0.5)
        max_daily_loss = _float_env("MAX_DAILY_LOSS_PCT", 5.0)
        min_balance = _float_env("MIN_ACCOUNT_BALANCE", 0.0)

        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")

        # пробуем core.config
        try:
            from core.config import Config as CoreConfig
            try:
                from core.types import TradingMode  # если есть Enum
                mode_value = TradingMode(mode)
            except Exception:
                mode_value = mode

            cfg_kwargs = dict(
                mode=mode_value,
                dry_run=dry_run,
                testnet=testnet,
                save_reports=True,
                binance_api_key=api_key,
                binance_api_secret=api_secret,
                timeframe=tf,
                leverage=lev,
                risk_per_trade_pct=risk_pct,
                max_daily_loss_pct=max_daily_loss,
                symbols=symbols,
            )
            # pydantic Config может ругаться на неизвестные — попробуем создать
            cfg = CoreConfig(**cfg_kwargs)
            # гарантируем min_account_balance
            if not hasattr(cfg, "min_account_balance"):
                # pydantic не любит setattr на поля — обойдём: добавим атрибут в __dict__ если возможно
                try:
                    object.__setattr__(cfg, "min_account_balance", min_balance)  # pydantic BaseModel
                except Exception:
                    try:
                        setattr(cfg, "min_account_balance", min_balance)
                    except Exception:
                        pass
            return cfg
        except Exception:
            # Минимальный fallback Config
            class _FallbackConfig:
                def __init__(self):
                    self.mode = mode
                    self.dry_run = dry_run
                    self.testnet = testnet
                    self.save_reports = True
                    self.binance_api_key = api_key
                    self.binance_api_secret = api_secret
                    self.timeframe = tf
                    self.leverage = lev
                    self.risk_per_trade_pct = risk_pct
                    self.max_daily_loss_pct = max_daily_loss
                    self.symbols = symbols
                    self.min_account_balance = min_balance

                def __repr__(self):
                    return (f"Config(mode={self.mode!r}, dry_run={self.dry_run}, testnet={self.testnet}, "
                            f"timeframe={self.timeframe!r}, leverage={self.leverage}, "
                            f"risk_per_trade_pct={self.risk_per_trade_pct}, max_daily_loss_pct={self.max_daily_loss_pct}, "
                            f"min_account_balance={self.min_account_balance}, symbols={self.symbols})")
            return _FallbackConfig()

    # ---------- команды CLI ----------
    @app.command()
    def paper(
        config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to .env.* file"),
        symbols: List[str] = typer.Option(["BTCUSDT"], "--symbols", help="Comma-separated or repeatable symbols"),
        timeframe: Optional[str] = typer.Option(None, "--timeframe", help="Override timeframe (e.g. 1m)"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose/diagnostic output"),
        testnet: bool = typer.Option(True, "--testnet/--no-testnet", help="Use testnet endpoints"),
        dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Do not send real orders"),
    ):
        """Paper trading mode (без реальных ордеров)."""
        # допускаем symbols="BTCUSDT,ETHUSDT"
        if len(symbols) == 1 and "," in symbols[0]:
            symbols = [s.strip().upper() for s in symbols[0].split(",") if s.strip()]
        _load_env_file(config)
        cfg = _build_config("paper", symbols, timeframe, testnet, dry_run)
        _print_config_table("paper", symbols, os.getenv("TIMEFRAME", timeframe or "1m"),
                            _int_env("LEVERAGE", 5),
                            _float_env("RISK_PER_TRADE_PCT", 0.5),
                            _float_env("MAX_DAILY_LOSS_PCT", 5.0),
                            testnet, dry_run)
        try:
            from runner.paper import run_paper_trading
        except Exception as e:
            console.print(f"[red]Cannot import runner.paper.run_paper_trading: {e}[/]")
            raise typer.Exit(1)
        try:
            asyncio.run(run_paper_trading(cfg))
        except KeyboardInterrupt:
            console.print("[yellow]Interrupted by user[/]")
        except Exception as e:
            console.print(f"[red]Paper trading failed: {e}[/]")
            raise typer.Exit(1)

    @app.command()
    def live(
        config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to .env.* file"),
        symbols: List[str] = typer.Option(["BTCUSDT"], "--symbols", help="Comma-separated or repeatable symbols"),
        timeframe: Optional[str] = typer.Option(None, "--timeframe", help="Override timeframe (e.g. 1m)"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose/diagnostic output"),
        testnet: bool = typer.Option(False, "--testnet/--no-testnet", help="Use testnet endpoints"),
        dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run", help="Do not send real orders"),
    ):
        """Live trading mode."""
        # допускаем symbols="BTCUSDT,ETHUSDT"
        if len(symbols) == 1 and "," in symbols[0]:
            symbols = [s.strip().upper() for s in symbols[0].split(",") if s.strip()]
        _load_env_file(config)

        # safety banner (если real live)
        if not dry_run:
            ok = typer.confirm("Are you sure you want to trade with real money?")
            if not ok:
                raise typer.Abort()

        cfg = _build_config("live", symbols, timeframe, testnet, dry_run)
        _print_config_table("live", symbols, os.getenv("TIMEFRAME", timeframe or "1m"),
                            _int_env("LEVERAGE", 5),
                            _float_env("RISK_PER_TRADE_PCT", 0.5),
                            _float_env("MAX_DAILY_LOSS_PCT", 5.0),
                            testnet, dry_run)
        try:
            from runner.live import run_live_trading
        except Exception as e:
            console.print(f"[red]Cannot import runner.live.run_live_trading: {e}[/]")
            raise typer.Exit(1)
        try:
            asyncio.run(run_live_trading(cfg))
        except KeyboardInterrupt:
            console.print("[yellow]Interrupted by user[/]")
        except Exception as e:
            console.print(f"[red]Live trading failed: {e}[/]")
            raise typer.Exit(1)

    if __name__ == "__main__":
        app()
    """).lstrip("\n")

    target.write_text(code, encoding="utf-8")
    print(f"✅ Wrote {target.relative_to(ROOT)}")

def patch_runner_live():
    """Фиксы для runner/live.py: getattr и безопасный min_account_balance."""
    target = ROOT / "runner" / "live.py"
    if not target.exists():
        print("ℹ️  runner/live.py not found — skip")
        return
    backup(target)
    txt = target.read_text(encoding="utf-8")

    # 1) Грубая правка ошибочного вызова self.getattr(...)
    txt = txt.replace("self.getattr(", "getattr(")

    # 2) Безопасный доступ к min_account_balance в любых сравнениях
    #    пример: balance < self.config.min_account_balance  ->  balance < getattr(self.config, 'min_account_balance', 0.0)
    txt = re.sub(
        r"balance\s*<\s*self\.config\.min_account_balance",
        r"balance < getattr(self.config, 'min_account_balance', 0.0)",
        txt,
    )
    txt = re.sub(
        r"self\.config\.min_account_balance",
        r"getattr(self.config, 'min_account_balance', 0.0)",
        txt,
    )

    target.write_text(txt, encoding="utf-8")
    print(f"✅ Patched {target.relative_to(ROOT)}")

def main():
    write_cli_integrated()
    patch_runner_live()
    print("\nDone. Now try:")
    print("  python cli_integrated.py paper --config .env.testnet --symbols BTCUSDT --verbose")
    print("  python cli_integrated.py live --config .env.testnet --symbols BTCUSDT,ETHUSDT --dry-run --testnet --verbose")

if __name__ == "__main__":
    main()

