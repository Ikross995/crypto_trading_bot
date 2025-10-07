# apply_orders_enum_compat_patch.py
from __future__ import annotations
import re, shutil
from pathlib import Path

OK = "\u2705"; WARN = "\u26A0\uFE0F"
BASE = Path(__file__).resolve().parent
ORDERS = BASE / "exchange" / "orders.py"

HELPERS = '''
# --- ENUM/str normalization helpers (idempotent) ---
def _as_side(v):
    try: return v.value
    except Exception:
        s = str(v).upper()
        if s in ("BUY","SELL"): return s
        if s in ("LONG","+","B","OPEN_LONG"):  return "BUY"
        if s in ("SHORT","-","S","OPEN_SHORT"): return "SELL"
        return "BUY"

def _as_tif(v):
    try: return v.value
    except Exception:
        s = str(v).upper()
        return s if s in ("GTC","IOC","FOK","GTX") else "GTC"

def _as_working_type(v):
    try: return v.value
    except Exception:
        s = str(v).upper()
        return s if s in ("MARK_PRICE","CONTRACT_PRICE") else "MARK_PRICE"
'''

def backup(p: Path, suf=".bak_orders"): 
    if p.exists(): shutil.copy2(p, p.with_suffix(p.suffix + suf))

def inject_helpers(txt: str) -> tuple[str,bool]:
    if "_as_side" in txt: return txt, False
    # вставим helpers после импортов
    lines = txt.splitlines(); idx = 0
    for i,l in enumerate(lines[:120]):
        if l.strip().startswith(("import ","from ")): idx = i+1
        elif l.strip()=="" or l.strip().startswith(("#",'"""',"'''")): continue
        else: break
    new = lines[:idx] + [HELPERS.strip(),""] + lines[idx:]
    return "\n".join(new)+("\n" if not txt.endswith("\n") else ""), True

def normalize_header(txt: str, fname: str, assigns: list[str]) -> tuple[str,bool]:
    pat = re.compile(rf"(def\s+{fname}\s*\([^)]*\)\s*:\s*\n)(\s+)")
    m = pat.search(txt); 
    if not m: return txt, False
    start = m.end(1); indent = m.group(2)
    body = txt[start:start+500]
    if all(a in body for a in assigns): return txt, False
    patch = "".join(f"{indent}{a}\n" for a in assigns)
    return txt[:start]+patch+txt[start:], True

def replace_value(txt: str) -> tuple[str,bool]:
    changed=False; out=txt
    maps = {
        r"\bside\.value\b":"side",
        r"\btime_in_force\.value\b":"time_in_force",
        r"\btimeInForce\.value\b":"timeInForce",
        r"\bworking_type\.value\b":"working_type",
        r"\bworkingType\.value\b":"workingType",
    }
    for p,r in maps.items():
        new = re.sub(p, r, out)
        if new!=out: changed=True; out=new
    return out, changed

def main():
    if not ORDERS.exists():
        print(f"{WARN} {ORDERS} not found"); return
    backup(ORDERS)
    txt = ORDERS.read_text(encoding="utf-8", errors="ignore")
    anyc=False
    txt1,ch1 = inject_helpers(txt); anyc|=ch1
    txt2,ch2 = normalize_header(txt1,"place_market_order",["try:\n        side = _as_side(side)\n    except NameError:\n        pass"]); anyc|=ch2
    txt3,ch3 = normalize_header(txt2,"place_limit_order",[
        "try:\n        side = _as_side(side)\n    except NameError:\n        pass",
        "try:\n        time_in_force = _as_tif(time_in_force)\n    except NameError:\n        pass",
    ]); anyc|=ch3
    txt4,ch4 = normalize_header(txt3,"place_stop_market_order",[
        "try:\n        side = _as_side(side)\n    except NameError:\n        pass",
        "try:\n        working_type = _as_working_type(working_type)\n    except NameError:\n        pass",
    ]); anyc|=ch4
    txt5,ch5 = replace_value(txt4); anyc|=ch5
    if anyc:
        ORDERS.write_text(txt5, encoding="utf-8")
        print(f"{OK} Patched {ORDERS.relative_to(BASE)} (enum/str compatibility)")
    else:
        print(f"{OK} {ORDERS.relative_to(BASE)} already compatible")

if __name__=="__main__":
    main()
