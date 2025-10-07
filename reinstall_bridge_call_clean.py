# reinstall_bridge_call_clean.py
from __future__ import annotations
import re, shutil
from pathlib import Path

OK = "\u2705"; WARN = "\u26A0\uFE0F"
BASE = Path(__file__).resolve().parent  # запуск из crypto_trading_bot/work
FILES = [BASE/"runner"/"paper.py", BASE/"runner"/"live.py"]

BRIDGE_SNIPPET = """{indent}# ORDER BRIDGE: executor path (clean reinstall)
{indent}try:
{indent}    _bridge_enabled = (getattr(self.config, "order_bridge_enable", False) or os.getenv("ORDER_BRIDGE_ENABLE","false").lower()=="true")
{indent}    if _bridge_enabled and {sigvar} and isinstance({sigvar}, dict) and {sigvar}.get("signal_type") in ("BUY","SELL"):
{indent}        if getattr(self, "trade_executor", None) and getattr(self.trade_executor, "client", None) is None and getattr(self, "client", None):
{indent}            self.trade_executor.client = self.client
{indent}        res = await asyncio.to_thread(
{indent}            self.trade_executor.handle_signal,
{indent}            symbol,
{indent}            {sigvar},
{indent}            working_type=getattr(self.config, "exit_working_type", "MARK_PRICE"),
{indent}        )
{indent}        self.logger.info("EXECUTOR RESULT %s: %s", symbol, res)
{indent}        # disable legacy path in this iteration
{indent}        {sigvar} = None
{indent}except Exception as _ex:
{indent}    self.logger.warning("ORDER BRIDGE error: %s", _ex)
"""

def backup(p: Path, suf=".bak_bridge"):
    if p.exists(): shutil.copy2(p, p.with_suffix(p.suffix + suf))

def ensure_imports(txt: str) -> tuple[str,bool]:
    changed=False
    lines = txt.splitlines()
    insert_idx = 0
    for i,l in enumerate(lines[:100]):
        if l.strip().startswith(("import ","from ")): insert_idx = i+1
        elif l.strip()=="" or l.lstrip().startswith(("#",'"""',"'''")): continue
        else: break
    need_os       = not any(re.match(r"\s*import\s+os(\s|,|$)", l) for l in lines)
    need_asyncio  = not any(re.match(r"\s*import\s+asyncio(\s|,|$)", l) for l in lines)
    need_exec     = not any("from runner.execution import TradeExecutor" in l for l in lines)
    ins=[]
    if need_os: ins.append("import os")
    if need_asyncio: ins.append("import asyncio")
    if need_exec: ins.append("from runner.execution import TradeExecutor")
    if ins:
        lines[insert_idx:insert_idx] = ins
        changed=True
    return "\n".join(lines)+("\n" if not txt.endswith("\n") else ""), changed

def remove_old_bridge_blocks(txt: str) -> tuple[str,bool]:
    changed=False
    lines = txt.splitlines()
    out=[]; i=0
    while i < len(lines):
        if "ORDER BRIDGE:" in lines[i]:
            # выкинуть блок до первой строки с 'except Exception as _ex:'
            j=i
            end=None
            while j < len(lines):
                if lines[j].lstrip().startswith("except Exception as _ex:"):
                    end = min(j+2, len(lines))  # плюс строка логгера, если есть
                    break
                j+=1
            if end is None:
                # если блок кривой — выкинем только текущую строку
                i+=1; changed=True
                continue
            i = end; changed=True
            continue
        out.append(lines[i]); i+=1
    txt2 = "\n".join(out)+("\n" if not txt.endswith("\n") else "")
    # подчистим одиночные 'sig = ...'
    txt3 = re.sub(r"^\s*sig\s*=.*?$", "", txt2, flags=re.MULTILINE)
    if txt3 != txt: changed=True
    return txt3, changed

def inject_bridge_after_generate(txt: str) -> tuple[str,bool]:
    """
    Найдём строку вида:   <sigvar> = ...generate_signal(...
    и вставим мост сразу после неё.
    """
    lines = txt.splitlines()
    pat = re.compile(r"^(\s*)(\w+)\s*=\s*.*generate_signal\s*\(", re.IGNORECASE)
    for idx, line in enumerate(lines):
        m = pat.match(line)
        if not m: continue
        indent, sigvar = m.group(1), m.group(2)
        # если уже есть clean reinstall — пропустим
        if "ORDER BRIDGE: executor path (clean reinstall)" in "\n".join(lines[idx: idx+20]):
            return txt, False
        snippet = BRIDGE_SNIPPET.format(indent=indent, sigvar=sigvar).rstrip("\n")
        lines.insert(idx+1, snippet)
        return "\n".join(lines)+("\n" if not txt.endswith("\n") else ""), True
    return txt, False

def ensure_executor_init_and_bind(txt: str) -> tuple[str,bool]:
    changed=False
    t=txt
    # 1) создать self.trade_executor = TradeExecutor() в __init__, если нет
    if "self.trade_executor = TradeExecutor()" not in t:
        m = re.search(r"(def\s+__init__\s*\([^)]*\)\s*:\s*\n)(\s+)", t)
        if m:
            pos=m.end(1); indent=m.group(2)
            t = t[:pos] + f"{indent}self.trade_executor = TradeExecutor()\n" + t[pos:]
            changed=True
    # 2) привязать client сразу после self.client = ...
    lines = t.splitlines(); out=[]; i=0; bound=False
    while i < len(lines):
        l = lines[i]; out.append(l)
        if "self.client =" in l and "self.trade_executor.client = self.client" not in "\n".join(lines[i:i+6]):
            ind = re.match(r"^(\s*)", l).group(1)
            out.append(f'{ind}if getattr(self, "trade_executor", None): self.trade_executor.client = self.client')
            bound=True
        i+=1
    if bound: 
        t2="\n".join(out)+("\n" if not t.endswith("\n") else "")
        return t2, True or changed
    return t, changed

def process_file(p: Path):
    if not p.exists():
        print(f"{WARN} {p} not found, skip"); return
    src = p.read_text(encoding="utf-8", errors="ignore")
    backup(p)
    t1,ch1 = ensure_imports(src)
    t2,ch2 = remove_old_bridge_blocks(t1)
    t3,ch3 = inject_bridge_after_generate(t2)
    t4,ch4 = ensure_executor_init_and_bind(t3)
    if any([ch1,ch2,ch3,ch4]):
        p.write_text(t4, encoding="utf-8")
        print(f"{OK} Patched {p.relative_to(BASE)}")
    else:
        print(f"{OK} {p.relative_to(BASE)} already ok")

def main():
    for f in FILES: process_file(f)
    print("\nDone.")
if __name__ == "__main__":
    main()
