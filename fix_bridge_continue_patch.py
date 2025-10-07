# fix_bridge_continue_patch.py
from __future__ import annotations
import re, shutil
from pathlib import Path

OK = "\u2705"
WARN = "\u26A0\uFE0F"

BASE = Path(__file__).resolve().parent  # предполагаем запуск из crypto_trading_bot/work

def backup(path: Path, suffix: str = ".bak2"):
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + suffix))

def patch_file(p: Path) -> bool:
    if not p.exists():
        print(f"{WARN} {p} not found, skip")
        return False

    txt = p.read_text(encoding="utf-8", errors="ignore")

    # Ищем наш ранее вставленный блок
    if "ORDER BRIDGE: executor path" not in txt:
        print(f"{WARN} {p} has no ORDER BRIDGE block, skip")
        return False

    lines = txt.splitlines()
    changed = False

    # Найдём строку if _bridge_enabled and <sigvar> and isinstance(<sigvar>, dict) ...
    pat_if = re.compile(
        r'^(\s*)if\s+_bridge_enabled\s+and\s+(\w+)\s+and\s+isinstance\(\2,\s*dict\)\s+and\s+\2\.get\("signal_type"\)\s+in\s+\("BUY","SELL"\):\s*$'
    )

    i = 0
    while i < len(lines):
        m = pat_if.match(lines[i])
        if not m:
            i += 1
            continue

        indent = m.group(1)
        sigvar = m.group(2)

        # В пределах следующих ~20 строк ищем строку "continue" внутри блока и меняем её на "<sigvar> = None"
        replaced_here = False
        for j in range(i + 1, min(i + 25, len(lines))):
            # пропустим вложенные конструкции, но нам нужен ровно тот continue, который мы вставляли
            if lines[j].strip() == "continue" and lines[j].startswith(indent):
                lines[j] = f"{indent}{sigvar} = None"
                changed = True
                replaced_here = True
                break
        if not replaced_here:
            # иногда отступ мог отличаться на +4 пробела; попробуем мягкий поиск
            for j in range(i + 1, min(i + 25, len(lines))):
                if lines[j].strip() == "continue":
                    # заменим на безопасное гашение сигнала
                    leading = re.match(r"^(\s*)", lines[j]).group(1)
                    lines[j] = f"{leading}{sigvar} = None"
                    changed = True
                    break
        i += 1

    if changed:
        backup(p)
        p.write_text("\n".join(lines) + ("\n" if not txt.endswith("\n") else ""), encoding="utf-8")
        print(f"{OK} Patched {p.relative_to(BASE)} (continue → <sigvar>=None)")
        return True
    else:
        print(f"{OK} {p.relative_to(BASE)} already fixed or no continue found")
        return False

def main():
    changed = 0
    for rel in ("runner/paper.py", "runner/live.py"):
        if patch_file(BASE / rel):
            changed += 1
    print("\nSummary:")
    print(f"  Fixed files: {changed}")
    print("\nDone.")

if __name__ == "__main__":
    main()
