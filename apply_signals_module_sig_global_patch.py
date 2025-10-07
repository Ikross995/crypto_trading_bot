# apply_signals_module_sig_global_patch.py
import re, shutil
from pathlib import Path

OK   = "\u2705"
WARN = "\u26A0\uFE0F"

BASE   = Path(__file__).resolve().parent
TARGET = BASE / "strategy" / "signals.py"

GUARD_BLOCK = """# --- Auto-guards for legacy 'sig' logging (idempotent) ---
try:
    sig
except NameError:
    sig = None
try:
    signal
except NameError:
    signal = None
try:
    trade_signal
except NameError:
    trade_signal = None
"""

def backup(p: Path, suf=".bak_sigglobal"):
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + suf))

def find_insert_index(lines):
    i = 0
    # shebang / encoding
    if i < len(lines) and lines[i].startswith("#!"):
        i += 1
    if i < len(lines) and "coding" in lines[i]:
        i += 1
    # пустые/комментарии
    while i < len(lines) and (lines[i].strip() == "" or lines[i].lstrip().startswith("#")):
        i += 1
    # from __future__ импорт(ы) должны быть самым верхним кодом — пропустим их
    while i < len(lines) and lines[i].strip().startswith("from __future__ import"):
        i += 1
    # возможные пустые/комменты после future
    while i < len(lines) and (lines[i].strip() == "" or lines[i].lstrip().startswith("#")):
        i += 1
    return i

def patch_text(txt: str) -> tuple[str, bool]:
    # если блок уже вставлен — пропускаем
    if "Auto-guards for legacy 'sig' logging" in txt:
        return txt, False
    lines = txt.splitlines(True)
    ins_idx = find_insert_index(lines)
    lines[ins_idx:ins_idx] = [GUARD_BLOCK + "\n"]
    return "".join(lines), True

def main():
    if not TARGET.exists():
        print(f"{WARN} {TARGET} not found. Abort."); return
    src = TARGET.read_text(encoding="utf-8", errors="ignore")
    new, changed = patch_text(src)
    if changed:
        backup(TARGET)
        TARGET.write_text(new, encoding="utf-8")
        print(f"{OK} Patched {TARGET.relative_to(BASE)} (module-level guards added)")
    else:
        print(f"{OK} {TARGET.relative_to(BASE)} already has module-level guards")

if __name__ == "__main__":
    main()
