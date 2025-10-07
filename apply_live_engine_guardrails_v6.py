# apply_live_engine_guardrails_v6.py
import re, sys, shutil
from pathlib import Path

LIVE = Path("runner/live.py")
if not LIVE.exists():
    print("runner/live.py not found")
    sys.exit(1)

src = LIVE.read_text(encoding="utf-8")
bak = LIVE.with_suffix(".bak_guardrails_v6.py")
shutil.copyfile(LIVE, bak)

txt = src

# 1) import inspect (для awaitable checks, если вдруг пригодится)
if "import inspect" not in txt:
    txt = txt.replace("import asyncio\nimport signal", "import asyncio\nimport signal\nimport inspect")

# 2) после self.processed_signals добавить локальные кулдауны
txt = re.sub(
    r"(self\.processed_signals:[^\n]+\n)",
    r"\1        # Local per-symbol cooldowns (engine-level)\n        self._cooldown_until: dict[str, datetime] = {}\n",
    txt,
    count=1,
)

# 3) заменить await self.order_manager.is_in_cooldown(...) на локальную проверку
txt = txt.replace(
    "if await self.order_manager.is_in_cooldown(signal.symbol):",
    "if self._is_in_cooldown(signal.symbol):"
)

# 4) заменить прямой вызов risk_manager.calculate_position_size(...) на безопасный wrapper
txt = txt.replace(
    "position_size = self.risk_manager.calculate_position_size(",
    "position_size = self._safe_calc_position_size(",
)

# 5) заменить случайные self.logger.info(...) -> logger.info(...)
txt = txt.replace("self.logger.info(", "logger.info(")

# 6) безопасная версия _is_trading_hours
def replace_method(body_name, new_body):
    # заменяет тело метода класса LiveTradingEngine с заданным именем
    pattern = rf"(def {body_name}\(self[^\)]*\):\n)(?:\s+.*\n)+?"
    # найти старт
    m = re.search(rf"\n\s+def {body_name}\(", txt)
    if not m:
        return False
    start = m.start()
    # найти конец методом поиска следующего def/async def на том же уровне отступов
    tail = txt[start+1:]
    m2 = re.search(r"\n\s+def |\n\s+async def ", tail)
    end = (start+1+m2.start()) if m2 else len(txt)
    head = txt[:start]
    chunk = txt[start:end]
    # заголовок (первая строка)
    hdr_end = chunk.find(":\n") + 2
    new_chunk = chunk[:hdr_end] + new_body
    new_txt = head + new_chunk + txt[end:]
    globals()['txt'] = new_txt
    return True

is_tr_hours_body = """\
        \"\"\"Check if we're in allowed trading hours.\"\"\"
        enabled = getattr(self.config, \"trading_hours_enabled\", False)
        if not enabled:
            return True
        now_h = datetime.utcnow().hour
        start = int(getattr(self.config, \"trading_start_hour\", 0))
        end   = int(getattr(self.config, \"trading_end_hour\", 23))
        if start <= end:
            return start <= now_h <= end
        else:
            # окно через полночь, напр. 22->5
            return not (end < now_h < start)
"""

replace_method("_is_trading_hours", is_tr_hours_body)

# 7) безопасная версия _check_emergency_stop (дефолты + баланс)
check_body = """\
        \"\"\"Check for emergency stop conditions.\"\"\"
        # Daily loss limit (в абсолюте, если указано)
        daily_pnl = await self.metrics.get_daily_pnl()
        max_daily_loss = float(getattr(self.config, \"max_daily_loss\", 0.0))
        if max_daily_loss and daily_pnl < -abs(max_daily_loss):
            logger.critical(f\"Daily loss limit exceeded: {format_currency(daily_pnl)}\")
            return True

        # Account balance (дефолт 0.0 — не стопаем, если параметр не задан)
        balance = 0.0
        try:
            b = self.position_manager.get_account_balance()
            balance = (await b) if inspect.isawaitable(b) else float(b or 0.0)
        except Exception as e:
            logger.warning(f\"Failed to read account balance: {e}\")
        min_bal = float(getattr(self.config, \"min_account_balance\", 0.0))
        if min_bal and balance < min_bal:
            logger.critical(f\"Account balance too low: {format_currency(balance)}\")
            return True

        # Max drawdown (доля от 0..1)
        max_dd = float(getattr(self.config, \"max_drawdown\", 1.0))
        try:
            dd = await self.metrics.get_max_drawdown()
        except Exception:
            dd = 0.0
        if dd > max_dd:
            logger.critical(f\"Maximum drawdown exceeded: {dd:.2%}\")
            return True

        return False
"""
replace_method("_check_emergency_stop", check_body)

# 8) после _setup_signal_handlers добавим два новых помощника: _is_in_cooldown и _bump_cooldown,
#    и безопасный расчёт размера позиции _safe_calc_position_size
insert_after = re.search(r"\n\s+def _setup_signal_handlers\(self\)[\s\S]*?\n\s+async def _run_trading_loop", txt)
if insert_after:
    p1, p2 = insert_after.span()
    before = txt[:p2 - len("async def _run_trading_loop")]
    after  = txt[p2 - len("async def _run_trading_loop"):]
    helpers = """
    def _is_in_cooldown(self, symbol: str) -> bool:
        \"\"\"Engine-level cooldown, не зависит от OrderManager.\"\"\"
        now = datetime.utcnow()
        until = self._cooldown_until.get(symbol)
        return bool(until and now < until)

    def _bump_cooldown(self, symbol: str) -> None:
        sec = int(getattr(self.config, "cooldown_sec", getattr(self.config, "cooldown_seconds", 0)) or 0)
        if sec > 0:
            self._cooldown_until[symbol] = datetime.utcnow() + timedelta(seconds=sec)

    def _safe_calc_position_size(self, signal, current_position):
        \"\"\"Обёртка над RiskManager.calculate_position_size: tuple->float, /0 защита.\"\"\"
        try:
            size = self.risk_manager.calculate_position_size(signal, current_position)
            # иногда стратегии возвращают (size, meta) — берём первый элемент
            if isinstance(size, tuple):
                size = size[0]
            return float(size)
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0.0

"""
    txt = before + helpers + after

# 9) после успешной отправки ордера в _process_signal ставим локальный кулдаун
txt = txt.replace(
    "if order:\n                self.pending_orders[order.id] = order\n                logger.info(f\"Order placed: {order.side} {order.quantity} {symbol}\")",
    "if order:\n                self.pending_orders[order.id] = order\n                logger.info(f\"Order placed: {order.side} {order.quantity} {symbol}\")\n                self._bump_cooldown(symbol)"
)

LIVE.write_text(txt, encoding="utf-8")
print(f"Patched {LIVE} -> backup: {bak.name}")
