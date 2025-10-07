# apply_compat_sig_global_patch.py
import re, shutil
from pathlib import Path

OK   = "\u2705"
WARN = "\u26A0\uFE0F"

BASE = Path(__file__).resolve().parent
CANDIDATES = [BASE/"compat_complete.py", BASE/"compat.py"]

BLOCK = """# --- GLOBAL SIG GUARD (builtins, idempotent) ---
import builtins as _blt
if not hasattr(_blt, "sig"):
    _blt.sig = None
if not hasattr(_blt, "signal"):
    _blt.signal = None
if not hasattr(_blt, "trade_signal"):
    _blt.trade_signal = None
"""

def backup(p: Path, suf=".bak_sigbuiltins"):
    if p.exists(): shutil.copy2(p, p.with_suffix(p.suffix + suf))

def insert_guard(txt: str) -> tuple[str,bool]:
    if "GLOBAL SIG GUARD (builtins" in txt:
        return txt, False
    lines = txt.splitlines()
    ins_idx = 0
    # shebang/encoding
    if ins_idx < len(lines) and lines[ins_idx].startswith("#!"):
        ins_idx += 1
    if ins_idx < len(lines) and "coding" in lines[ins_idx]:
        ins_idx += 1
    # пустые/комменты
    while ins_idx < len(lines) and (lines[ins_idx].strip()=="" or lines[ins_idx].lstrip().startswith("#")):
        ins_idx += 1
    # future-imports
    while ins_idx < len(lines) and lines[ins_idx].strip().startswith("from __future__ import"):
        ins_idx += 1
    # пустые/комменты после future
    while ins_idx < len(lines) and (lines[ins_idx].strip()=="" or lines[ins_idx].lstrip().startswith("#")):
        ins_idx += 1
    # вставка блока
    lines[ins_idx:ins_idx] = [BLOCK.strip(), ""]
    return "\n".join(lines) + ("\n" if not txt.endswith("\n") else ""), True

def patch_one(p: Path):
    if not p.exists(): 
        print(f"{WARN} {p.name} not found, skip"); 
        return
    src = p.read_text(encoding="utf-8", errors="ignore")
    new, changed = insert_guard(src)
    if changed:
        backup(p)
        p.write_text(new, encoding="utf-8")
        print(f"{OK} Patched {p.name} (global sig guard)")
    else:
        print(f"{OK} {p.name} already has global sig guard")

def main():
    any_found = False
    for f in CANDIDATES:
        if f.exists():
            any_found = True
            patch_one(f)
    if not any_found:
        print(f"{WARN} compat file not found (looked for: {', '.join(x.name for x in CANDIDATES)})")
    else:
        print("\nDone.")

if __name__ == "__main__":
    main()
