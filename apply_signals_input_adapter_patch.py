# apply_signals_input_adapter_patch.py
import re, shutil
from pathlib import Path

OK="✅"; WARN="⚠️"
BASE = Path(__file__).resolve().parent
TARGET = BASE / "strategy" / "signals.py"

BLOCK = r'''
# --- INPUT ADAPTER (idempotent) ---
def _coerce_market_input(symbol, market_data):
    """
    Превращаем разношёрстный market_data в (price, klines_like) без падений.
    price: float|None
    klines_like: list[(ts,o,h,l,c)]|None
    """
    sym = str(symbol or "UNKNOWN").upper()
    price = None
    klike = None

    try:
        # dict c 'price' или last
        if isinstance(market_data, dict):
            for k in ("price","last","last_price","close","c"):
                if k in market_data:
                    price = float(market_data[k]); break
            if "kline" in market_data and isinstance(market_data["kline"], (list,tuple)):
                kl = market_data["kline"]
                if kl and len(kl[0])>=5:
                    klike = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in kl]
        # list свечей
        elif isinstance(market_data, (list,tuple)) and market_data:
            # может быть список свечей [ [ts,o,h,l,c,...], ... ]
            if isinstance(market_data[0], (list,tuple)) and len(market_data[0])>=5:
                try:
                    klike = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in market_data]
                    price = float(klike[-1][4])
                except Exception:
                    pass
        # одиночные типы
        elif isinstance(market_data, (int,float)):
            price = float(market_data)
        elif isinstance(market_data, str):
            try: price = float(market_data)
            except Exception: pass
    except Exception:
        # не роняем генератор — просто возвращаем None
        pass

    return price, klike
# --- /INPUT ADAPTER ---
'''

def insert_block(txt:str)->str:
    if "def _coerce_market_input(" in txt:
        return txt
    # вставим после импортов
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

def tune_generate_signal(txt:str)->str:
    # На старте тела функции generate_signal(...) добавим:
    #   price, klike = _coerce_market_input(symbol, market_data)
    pat = re.compile(r'^(\s*)(?:async\s+)?def\s+generate_signal\s*\(([^)]*)\)\s*:\s*$', re.M)
    m = pat.search(txt)
    if not m: return txt
    indent = m.group(1)
    # найдём первую строку тела
    start = m.end()
    # найдём конец сигнатуры/докстроки
    body_idx = start
    lines = txt[body_idx:].splitlines(True)
    i = 0
    # пропустить пустые/докстроку
    if i < len(lines) and lines[i].strip()=="":
        i+=1
    if i < len(lines) and lines[i].lstrip().startswith(('"""',"'''")):
        q = '"""' if lines[i].lstrip().startswith('"""') else "'''"
        i+=1
        while i < len(lines):
            s = lines[i].strip()
            if s.endswith(q): i+=1; break
            i+=1
    # готова точка вставки
    INS = f"{indent}    price, klike = _coerce_market_input(symbol if 'symbol' in locals() else None, market_data)\n"
    # вставим если ещё не вставлено
    rest = "".join(lines)
    if "price, klike = _coerce_market_input(" in rest:
        return txt
    new_rest = rest[:0] + INS + rest
    return txt[:body_idx] + new_rest

def main():
    if not TARGET.exists():
        print(f"{WARN} {TARGET} not found"); return
    src = TARGET.read_text(encoding="utf-8", errors="ignore")
    new = insert_block(src)
    newer = tune_generate_signal(new)
    if newer != src:
        backup = TARGET.with_suffix(TARGET.suffix + ".bak_input")
        shutil.copy2(TARGET, backup)
        TARGET.write_text(newer, encoding="utf-8")
        print(f"{OK} Patched strategy/signals.py (input adapter added), backup: {backup.name}")
    else:
        print(f"{OK} strategy/signals.py already adapted")

if __name__ == "__main__":
    main()
