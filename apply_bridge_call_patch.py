# apply_bridge_call_patch.py
from __future__ import annotations
import re, shutil
from pathlib import Path

OK = "\u2705"
WARN = "\u26A0\uFE0F"

BASE = Path(__file__).resolve().parent  # предполагаем запуск из crypto_trading_bot/work

BRIDGE_SNIPPET_TEMPLATE = """{indent}# ORDER BRIDGE: executor path (idempotent)
{indent}try:
{indent}    _bridge_enabled = (getattr(self.config, "order_bridge_enable", False) or os.getenv("ORDER_BRIDGE_ENABLE","false").lower()=="true")
{indent}    if _bridge_enabled and {sigvar} and isinstance({sigvar}, dict) and {sigvar}.get("signal_type") in ("BUY","SELL"):
{indent}        # лениво привязываем клиента к исполнителю, если ещё не привязан
{indent}        if getattr(self, "trade_executor", None) and getattr(self.trade_executor, "client", None) is None and getattr(self, "client", None):
{indent}            self.trade_executor.client = self.client
{indent}        res = await asyncio.to_thread(
{indent}            self.trade_executor.handle_signal,
{indent}            symbol,
{indent}            {sigvar},
{indent}            working_type=getattr(self.config, "exit_working_type", "MARK_PRICE"),
{indent}        )
{indent}        self.logger.info("EXECUTOR RESULT %s: %s", symbol, res)
{indent}        # пропускаем легаси-путь ордеров для этой итерации
{indent}        continue
{indent}except Exception as _ex:
{indent}    self.logger.warning("ORDER BRIDGE error: %s", _ex)
"""

def backup(path: Path):
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

def ensure_top_imports(text: str) -> tuple[str, bool]:
    """Гарантируем наличие import os, import asyncio, from runner.execution import TradeExecutor."""
    changed = False
    lines = text.splitlines()
    # найдём блок импортов (первые 80 строк)
    insert_idx = 0
    for i, l in enumerate(lines[:80]):
        if l.strip().startswith(("import ", "from ")):
            insert_idx = i + 1
        elif l.strip() in ("",) or l.lstrip().startswith(("#", '"""', "'''")):
            continue
        else:
            break

    need_os = not any(re.match(r"\s*import\s+os(\s*|,)", l) for l in lines)
    need_asyncio = not any(re.match(r"\s*import\s+asyncio(\s*|,)", l) for l in lines)
    need_exec = not any("from runner.execution import TradeExecutor" in l for l in lines)

    ins_lines = []
    if need_os: ins_lines.append("import os")
    if need_asyncio: ins_lines.append("import asyncio")
    if need_exec: ins_lines.append("from runner.execution import TradeExecutor")

    if ins_lines:
        lines[insert_idx:insert_idx] = ins_lines
        changed = True

    return "\n".join(lines) + ("\n" if not text.endswith("\n") else ""), changed

def inject_bridge_after_generate(text: str) -> tuple[str, bool]:
    """
    Ищем присваивание вида:    <sigvar> = ...generate_signal(...)
    и вставляем мост сразу после этой строки (с корректным отступом).
    """
    if "ORDER BRIDGE: executor path" in text:
        return text, False  # уже вставлено

    lines = text.splitlines()
    pattern = re.compile(r"^(\s*)(\w+)\s*=\s*.*generate_signal\s*\(", re.IGNORECASE)
    for idx, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        indent, sigvar = m.group(1), m.group(2)
        snippet = BRIDGE_SNIPPET_TEMPLATE.format(indent=indent, sigvar=sigvar)
        lines.insert(idx + 1, snippet.rstrip("\n"))
        return "\n".join(lines) + ("\n" if not text.endswith("\n") else ""), True

    return text, False

def ensure_executor_init_and_bind(text: str) -> tuple[str, bool]:
    """
    На случай, если previous patch не применился:
    - создаём self.trade_executor = TradeExecutor() в __init__ (если нет)
    - после присвоения self.client = ... добавляем привязку к исполнителю
    """
    changed = False
    t = text

    # 1) ensure executor init
    if "self.trade_executor = TradeExecutor()" not in t:
        m = re.search(r"def\s+__init__\s*\([^)]*\)\s*:\s*\n", t)
        if m:
            # вставим сразу после объявления __init__
            pos = m.end()
            # определим базовый отступ из следующей строки
            after = t[pos:].splitlines()
            indent = ""
            if after:
                m2 = re.match(r"(\s*)", after[0])
                indent = m2.group(1) if m2 else "    "
            inject = f"{indent}self.trade_executor = TradeExecutor()\n"
            t = t[:pos] + inject + t[pos:]
            changed = True

    # 2) ensure client binding line after "self.client = ... "
    lines = t.splitlines()
    out = []
    i = 0
    modified_binding = False
    while i < len(lines):
        l = lines[i]
        out.append(l)
        if "self.client =" in l and "self.trade_executor.client = self.client" not in "\n".join(lines[i:i+5]):
            indent = re.match(r"(\s*)", l).group(1)
            out.append(f'{indent}if getattr(self, "trade_executor", None): self.trade_executor.client = self.client')
            modified_binding = True
        i += 1
    if modified_binding:
        t2 = "\n".join(out) + ("\n" if not t.endswith("\n") else "")
        return t2, True or changed
    return t, changed

def patch_runner(p: Path) -> bool:
    if not p.exists():
        print(f"{WARN} {p} not found, skip")
        return False
    backup(p)
    txt = p.read_text(encoding="utf-8", errors="ignore")
    any_change = False

    txt1, ch1 = ensure_top_imports(txt); any_change |= ch1
    txt2, ch2 = inject_bridge_after_generate(txt1); any_change |= ch2
    txt3, ch3 = ensure_executor_init_and_bind(txt2); any_change |= ch3

    if any_change:
        p.write_text(txt3, encoding="utf-8")
        print(f"{OK} Patched {p.relative_to(BASE)}")
        return True
    else:
        print(f"{OK} {p.relative_to(BASE)} already patched")
        return False

def main():
    changed = 0
    for rel in ("runner/paper.py", "runner/live.py"):
        p = BASE / rel
        if patch_runner(p):
            changed += 1
    print("\nSummary:")
    print(f"  Patched files: {changed}")
    print("\nDone.")

if __name__ == "__main__":
    main()
