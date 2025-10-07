# apply_live_engine_hotfix_v5.py
# Один проход по runner/live.py: чинит пропущенный ":", заменяет self.logger -> logger,
# добавляет дефолты для trading_interval и guarded emergency stop, а также
# делает безопасную проверку cooldown у OrderManager.

import re
from pathlib import Path

LIVE_PATH = Path("runner/live.py")

def replace_block(txt, start_pat, end_pat, new_block):
    m = re.search(start_pat, txt, flags=re.S)
    if not m:
        return txt, False
    start = m.start()
    m2 = re.search(end_pat, txt[m.end():], flags=re.S|re.M)
    if not m2:
        return txt, False
    end = m.end() + m2.start()
    return txt[:start] + new_block + txt[end:], True

def main():
    if not LIVE_PATH.exists():
        raise SystemExit("runner/live.py not found")

    src = LIVE_PATH.read_text(encoding="utf-8")
    bak = LIVE_PATH.with_suffix(".bak_hotfix_v5")
    bak.write_text(src, encoding="utf-8")

    changed = 0

    # 1) Починить пропущенный ":" в for symbol, position in list(self.active_positions.items())
    src2 = re.sub(
        r"(for\s+symbol\s*,\s*position\s+in\s+list\(\s*self\.active_positions\.items\(\)\s*\))\s*(\r?\n)",
        r"\1:\2",
        src
    )
    if src2 != src:
        changed += 1
    src = src2

    # 2) self.logger -> logger
    src2 = src.replace("self.logger.info(", "logger.info(")
    if src2 != src:
        changed += 1
    src = src2

    # 3) Дефолт для trading_interval
    src2 = re.sub(
        r"sleep_time\s*=\s*max\(0,\s*self\.config\.trading_interval\s*-\s*loop_duration\)",
        "interval = float(getattr(self.config, 'trading_interval', 1.0))\n"
        "                sleep_time = max(0, interval - loop_duration)",
        src
    )
    if src2 != src:
        changed += 1
    src = src2

    # 4) if self.config.dca_enabled -> getattr(..., False)
    src2 = re.sub(
        r"if\s+self\.config\.dca_enabled\s*:",
        "if getattr(self.config, 'dca_enabled', False):",
        src
    )
    if src2 != src:
        changed += 1
    src = src2

    # 5) if self.config.close_positions_on_exit -> getattr(..., False)
    src2 = re.sub(
        r"if\s+self\.config\.close_positions_on_exit\s*:",
        "if getattr(self.config, 'close_positions_on_exit', False):",
        src
    )
    if src2 != src:
        changed += 1
    src = src2

    # 6) Переписать _can_trade_signal с безопасной проверкой cooldown и лимита позиции
    can_trade_new = '''
    async def _can_trade_signal(self, signal: Signal) -> bool:
        """Check if we can trade a signal (safe guards)."""
        # Allowed symbols
        cfg_symbols = getattr(self.config, "symbols", []) or [getattr(self.config, "symbol", None)]
        if getattr(signal, "symbol", None) not in cfg_symbols:
            return False

        # Trading hours
        if not self._is_trading_hours():
            return False

        # Cooldown via OrderManager (supports async or sync, or missing)
        cooldown = False
        try:
            maybe = getattr(self.order_manager, "is_in_cooldown", None)
            if maybe:
                import asyncio as _aio
                if _aio.iscoroutinefunction(maybe):
                    cooldown = await maybe(signal.symbol)
                else:
                    cooldown = bool(maybe(signal.symbol))
        except Exception as e:
            logger.warning(f"Cooldown check failed: {e}")
        if cooldown:
            return False

        # Existing position size limit (optional)
        current_position = self.active_positions.get(signal.symbol)
        max_pos = float(getattr(self.config, "max_position_size", 0.0) or 0.0)
        if current_position and max_pos > 0:
            try:
                if abs(getattr(current_position, "size", 0.0)) >= max_pos:
                    return False
            except Exception:
                pass

        return True
    '''
    src2, ok = replace_block(
        src,
        r"async\s+def\s+_can_trade_signal\([^\)]*\):",
        r"^\s*def\s+_is_trading_hours",
        can_trade_new + "\n\n    def _is_trading_hours"
    )
    if ok:
        changed += 1
        src = src2

    # 7) Переписать _check_emergency_stop с getattr и try/except
    check_emergency_new = '''
    async def _check_emergency_stop(self) -> bool:
        """Check for emergency stop conditions (safe)."""
        # Daily loss
        try:
            daily_pnl = await self.metrics.get_daily_pnl()
        except Exception:
            daily_pnl = 0.0
        max_daily_loss = float(getattr(self.config, "max_daily_loss", getattr(self.config, "max_daily_loss_pct", 0.0)) or 0.0)
        if max_daily_loss and daily_pnl < -abs(max_daily_loss):
            logger.critical(f"Daily loss limit exceeded: {format_currency(daily_pnl)}")
            return True

        # Account balance
        try:
            balance = self.position_manager.get_account_balance()
        except Exception:
            balance = 0.0
        min_balance = float(getattr(self.config, "min_account_balance", 0.0) or 0.0)
        if min_balance and balance < min_balance:
            logger.critical(f"Account balance too low: {format_currency(balance)}")
            return True

        # Maximum drawdown
        try:
            max_drawdown = await self.metrics.get_max_drawdown()
        except Exception:
            max_drawdown = 0.0
        cfg_max_dd = float(getattr(self.config, "max_drawdown", 0.0) or 0.0)
        if cfg_max_dd and max_drawdown > cfg_max_dd:
            logger.critical(f"Maximum drawdown exceeded: {max_drawdown:.2%}")
            return True

        return False
    '''
    src2, ok = replace_block(
        src,
        r"async\s+def\s+_check_emergency_stop\([^\)]*\):",
        r"^\s*async\s+def\s+_health_check",
        check_emergency_new + "\n\n    async def _health_check"
    )
    if ok:
        changed += 1
        src = src2

    LIVE_PATH.write_text(src, encoding="utf-8")
    print(f"Patched runner/live.py. Changes applied: {changed}. Backup: {bak.name}")

if __name__ == "__main__":
    main()
