# purge_bridge_sig_refs.py
from __future__ import annotations
import re, shutil
from pathlib import Path

OK = "\u2705"; WARN = "\u26A0\uFE0F"
BASE = Path(__file__).resolve().parent

ANCHOR = "ORDER BRIDGE: executor path"
EXCEPT_LINE = "except Exception as _ex:"

NEW_BLOCK = """{indent}# ORDER BRIDGE: executor path (final safe)
{indent}try:
{indent}    _bridge_enabled = (getattr(self.config, "order_bridge_enable", False) or os.getenv("ORDER_BRIDGE_ENABLE","false").lower()=="true")
{indent}    _bridge_sig = None
{indent}    try:
{indent}        _loc = locals()
{indent}    except Exception:
{indent}        _loc = dict()
{indent}    for _n in ("signal","trade_signal","sig"):
{indent}        if _n in _loc:
{indent}            _bridge_sig = _loc.get(_n)
{indent}            break
{indent}    if _bridge_enabled and isinstance(_bridge_sig, dict) and _bridge_sig.get("signal_type") in ("BUY","SELL"):
{indent}        if getattr(self, "trade_executor", None) and getattr(self.trade_executor, "client", None) is None and getattr(self, "client", None):
{indent}            self.trade_executor.client = self.client
{indent}        res = await asyncio.to_thread(
{indent}            self.trade_executor.handle_signal,
{indent}            symbol,
{indent}            _bridge_sig,
{indent}            working_type=getattr(self.config, "exit_working_type", "MARK_PRICE"),
{indent}        )
{indent}        self.logger.info("EXECUTOR RESULT %s: %s", symbol, res)
{indent}{EXCEPT_LINE}
{indent}    self.logger.warning("ORDER BRIDGE error: %s", _ex)
"""

def backup(p: Path, suffix: str):
    if p.exists(): shutil.copy2(p, p.with_suffix(p.suffix + suffix))

def replace_bridge_block(txt: str) -> tuple[str, bool]:
    if ANCHOR not in txt: return txt, False
    lines = txt.splitlines()
    out = []; i = 0; changed = False
    while i < len(lines):
        if ANCHOR in lines[i]:
            indent = re.match(r"^(\s*)", lines[i]).group(1)
            # вырежем старый блок до except‑логгера
            j = i
            end = None
            while j < len(lines):
                if lines[j].lstrip().startswith(EXCEPT_LINE):
                    end = j + 1  # захватываем логгер после except
                    break
                j += 1
            if end is None:
                # если нет корректного конца — просто вставим новый блок вместо текущей строки
                out.append(NEW_BLOCK.format(indent=indent, EXCEPT_LINE=EXCEPT_LINE))
                i += 1; changed = True; continue
            # заменяем весь старый блок новым
            out.append(NEW_BLOCK.format(indent=indent, EXCEPT_LINE=EXCEPT_LINE))
            i = end; changed = True
            continue
        out.append(lines[i]); i += 1
    return "\n".join(out) + ("\n" if not txt.endswith("\n") else ""), changed

def strip_loose_sig_lines(txt: str) -> tuple[str, bool]:
    # подчистим случайные одиночные строки вида "sig = None"
    lines = txt.splitlines(); changed = False
    new_lines = []
    for l in lines:
        if re.match(r"^\s*sig\s*=", l):
            changed = True
            continue
        new_lines.append(l)
    return "\n".join(new_lines) + ("\n" if not txt.endswith("\n") else ""), changed

def patch_one(p: Path) -> bool:
    if not p.exists():
        print(f"{WARN} {p} not found, skip"); return False
    src = p.read_text(encoding="utf-8", errors="ignore")
    txt, ch1 = replace_bridge_block(src)
    txt2, ch2 = strip_loose_sig_lines(txt)
    if ch1 or ch2:
        backup(p, ".bak_sigfix")
        p.write_text(txt2, encoding="utf-8")
        print(f"{OK} Patched {p.relative_to(BASE)} (bridge fixed)")
        return True
    else:
        print(f"{OK} {p.relative_to(BASE)} already ok")
        return False

def main():
    changed = 0
    for rel in ("runner/paper.py", "runner/live.py"):
        if patch_one(BASE / rel): changed += 1
    print("\nSummary:\n  Updated files:", changed, "\nDone.")

if __name__ == "__main__":
    main()
