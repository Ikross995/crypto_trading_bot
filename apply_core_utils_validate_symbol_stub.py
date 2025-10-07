# apply_core_utils_validate_symbol_stub.py
from pathlib import Path
import re, shutil

OK = "✅"; WARN = "⚠️"
BASE = Path(__file__).resolve().parent
TARGET = BASE / "core" / "utils.py"

STUB = """
# --- compat stub: validate_symbol / normalize_symbol (idempotent) ---
def validate_symbol(sym: str) -> str:
    try:
        s = str(sym).strip().upper()
    except Exception:
        return ""
    # мягкая валидация: просто нормализуем регистр/пробелы
    return s

def normalize_symbol(sym: str) -> str:
    return validate_symbol(sym)
"""

def main():
    if not TARGET.exists():
        print(f"{WARN} {TARGET} not found"); return
    txt = TARGET.read_text(encoding="utf-8", errors="ignore")
    if "def validate_symbol" in txt:
        print(f"{OK} core/utils.py already provides validate_symbol()"); return
    # вставим после импортов
    lines = txt.splitlines(True)
    ins = 0
    for i, l in enumerate(lines[:150]):
        if l.strip().startswith(("import ", "from ")):
            ins = i + 1
        elif l.strip()=="" or l.strip().startswith(("#","'''","\"\"\"")):
            continue
        else:
            break
    lines[ins:ins] = [STUB.strip() + "\n\n"]
    backup = TARGET.with_suffix(TARGET.suffix + ".bak_validatesym")
    shutil.copy2(TARGET, backup)
    TARGET.write_text("".join(lines), encoding="utf-8")
    print(f"{OK} Patched core/utils.py (added validate_symbol/normalize_symbol), backup: {backup.name}")

if __name__ == "__main__":
    main()
