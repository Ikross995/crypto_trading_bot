# apply_compat_signal_side_map_patch.py
import re, shutil
from pathlib import Path

OK="✅"; WARN="⚠️"
BASE = Path(__file__).resolve().parent
CAND = [BASE/"compat_complete.py", BASE/"compat.py"]

PATCH_TAG = "COMPAT SIGNAL SIDE MAP PATCH"

BLOCK = r'''
# --- {tag} ---
def _compat_map_side(side: str) -> str:
    s = str(side or "").strip().upper()
    if s in ("BUY", "LONG", "L"):   return "LONG"
    if s in ("SELL","SHORT","S"):   return "SHORT"
    return "NONE"
# (интегрировать этот маппер в месте, где формируется normalized signal)
'''.format(tag=PATCH_TAG)

def integrate_block(txt: str) -> str:
    if PATCH_TAG in txt:
        return txt
    # вставим блок после импортов
    lines = txt.splitlines(True)
    ins = 0
    for i,l in enumerate(lines[:200]):
        if l.strip().startswith(("import ","from ")):
            ins = i+1
        elif l.strip()=="" or l.lstrip().startswith(("#",'"""',"'''")):
            continue
        else:
            break
    lines[ins:ins] = [BLOCK, "\n"]
    return "".join(lines)

def integrate_usage(txt: str) -> str:
    # заменим места, где строится normalized signal_type, на вызов _compat_map_side(...)
    # самые частые варианты:
    txt2 = re.sub(r"(signal_type\s*=\s*)str\(\s*sig(?:nal)?\s*\)\.upper\(\)", r"\1_compat_map_side(sig)", txt)
    txt2 = re.sub(r"(signal_type\s*=\s*)str\(\s*side\s*\)\.upper\(\)", r"\1_compat_map_side(side)", txt2)
    # если логи формируются напрямую — поправим сообщение «BUY»/«SELL» -> маппинга
    txt2 = re.sub(r'("signal_type"\s*:\s*)str\(\s*sig(?:nal)?\s*\)\.upper\(\)', r'\1_compat_map_side(sig)', txt2)
    return txt2

def patch_one(p: Path):
    if not p.exists():
        print(f"{WARN} {p} not found"); return
    src = p.read_text(encoding="utf-8", errors="ignore")
    new = integrate_usage(integrate_block(src))
    if new != src:
        backup = p.with_suffix(p.suffix + ".bak_sidemap")
        shutil.copy2(p, backup)
        p.write_text(new, encoding="utf-8")
        print(f"{OK} Patched {p.name} ({PATCH_TAG}), backup: {backup.name}")
    else:
        print(f"{OK} {p.name} already has side map patch")

def main():
    any_ = False
    for c in CAND:
        if c.exists():
            any_ = True; patch_one(c)
    if not any_:
        print(f"{WARN} compat file not found")
    else:
        print("\nDone.")

if __name__ == "__main__":
    main()
