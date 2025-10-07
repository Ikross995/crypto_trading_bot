# apply_signals_sig_autoguard_all.py
import re, shutil
from pathlib import Path

OK   = "\u2705"
WARN = "\u26A0\uFE0F"

BASE   = Path(__file__).resolve().parent
TARGET = BASE / "strategy" / "signals.py"

def backup(p: Path, suf=".bak_sigguard_all"):
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + suf))

def leading_spaces(s: str) -> int:
    return len(s) - len(s.lstrip(" "))

def is_def_or_class(line: str) -> bool:
    return bool(re.match(r'^\s*(?:async\s+)?def\s+\w+\s*\(|^\s*class\s+\w+\s*\(', line))

def find_func_block(lines, start_idx):
    """
    На входе: индекс строки с 'def ...:'
    Возвращает: (body_start_idx, body_indent_str, func_end_idx_exclusive)
    """
    header = lines[start_idx]
    indent = re.match(r'^(\s*)', header).group(1)
    i = start_idx + 1

    # пропустим пустые строки
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    # если докстрока
    if i < len(lines) and lines[i].lstrip().startswith(('"""',"'''")):
        quote = '"""' if lines[i].lstrip().startswith('"""') else "'''"
        # однострочная докстрока?
        if lines[i].rstrip().endswith(quote) and lines[i].strip() != quote:
            i += 1
        else:
            i += 1
            while i < len(lines):
                if lines[i].rstrip().endswith(quote):
                    i += 1
                    break
                i += 1

    # теперь i — первая строка тела функции
    # определим отступ тела
    if i < len(lines):
        m2 = re.match(r'^(\s*)', lines[i])
        body_indent = m2.group(1) if m2 else indent + "    "
    else:
        body_indent = indent + "    "

    # найдём конец функции — следующая def/class с отступом не больше, чем у функции
    j = i
    while j < len(lines):
        if is_def_or_class(lines[j]) and leading_spaces(lines[j]) <= leading_spaces(indent):
            break
        j += 1
    return i, body_indent, j

def function_uses_sig(body_lines):
    # есть ли упоминания sig в теле?
    return any(re.search(r'\bsig\b', ln) for ln in body_lines)

def function_defines_sig_early(body_lines):
    # определён ли sig в первых ~50 строках?
    limit = min(50, len(body_lines))
    for ln in body_lines[:limit]:
        if re.match(r'^\s*sig\s*=', ln):  # присваивание
            return True
    return False

def insert_guard(lines, body_start, body_indent):
    guard = f"{body_indent}sig = locals().get('signal', locals().get('trade_signal', None))  # auto-guard to avoid NameError\n"
    lines.insert(body_start, guard)
    return lines

def patch_text(txt: str) -> tuple[str, int]:
    lines = txt.splitlines(True)  # сохраняем \n
    i = 0
    changes = 0
    pat_header = re.compile(r'^(\s*)(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*:\s*$')

    while i < len(lines):
        if not pat_header.match(lines[i]):
            i += 1
            continue

        body_start, body_indent, func_end = find_func_block(lines, i)
        body = lines[body_start:func_end]

        # если функция упоминает sig, но рано не определяет — ставим гвард
        if function_uses_sig(body) and not function_defines_sig_early(body):
            lines = insert_guard(lines, body_start, body_indent)
            # сдвиг конца функции на одну строку вниз
            func_end += 1
            changes += 1

        i = func_end

    return "".join(lines), changes

def main():
    if not TARGET.exists():
        print(f"{WARN} {TARGET} not found. Abort.")
        return
    src = TARGET.read_text(encoding="utf-8", errors="ignore")
    new, n = patch_text(src)
    if n > 0:
        backup(TARGET)
        TARGET.write_text(new, encoding="utf-8")
        print(f"{OK} Patched {TARGET.relative_to(BASE)} — inserted guards in {n} function(s)")
    else:
        print(f"{OK} {TARGET.relative_to(BASE)} — no changes needed (guards present or no 'sig' usage)")

if __name__ == "__main__":
    main()
