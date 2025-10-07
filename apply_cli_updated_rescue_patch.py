# apply_cli_updated_rescue_patch.py
from __future__ import annotations
from pathlib import Path
import re, shutil, os

OK="✅"; WARN="⚠️"
BASE = Path(__file__).resolve().parent
TARGET = BASE/"cli_updated.py"

HELPER = r'''
# --- IMBA: apply env overrides for TESTNET/DRY_RUN (rescue, idempotent) ---
import os as _imba_os

def _imba_env_bool(name: str):
    v = _imba_os.getenv(name, None)
    if v is None: return None
    return str(v).strip().lower() in {"1","true","t","yes","y","on"}

def _imba_apply_env_overrides(cfg):
    try:
        et = _imba_env_bool("TESTNET")
        ed = _imba_env_bool("DRY_RUN")
        if et is not None:
            cfg.testnet = bool(et)
        if ed is not None:
            cfg.dry_run = bool(ed)
    except Exception:
        pass
# --- /IMBA helper ---
'''.strip()

def backup(p: Path, suf: str):
    if p.exists():
        bk = p.with_suffix(p.suffix + suf)
        shutil.copy2(p, bk)
        return bk.name
    return None

def insert_helper(txt: str) -> str:
    if "_imba_apply_env_overrides(" in txt:
        return txt
    lines = txt.splitlines(True)
    # вставим после импортов
    ins = 0
    for i,l in enumerate(lines[:300]):
        if l.strip().startswith(("import ","from ")):
            ins = i+1
        elif l.strip()=="" or l.strip().startswith(("#","'''",'"""')):
            continue
        else:
            break
    lines[ins:ins] = [HELPER+"\n\n"]
    return "".join(lines)

def inject_call_before_asyncio(txt: str, func_name: str, runner_call: str) -> str:
    # Ищем def ...:  и строку asyncio.run(run_...(config))
    # Вставим _imba_apply_env_overrides(config) за пару строк до asyncio.run(...)
    pat_func = re.compile(rf"(^\s*def\s+{func_name}\s*\(.*?\):\s*$)", re.M)
    m = pat_func.search(txt)
    if not m:
        return txt
    start = m.end()
    # ограничим область поиска телом функции до следующей "def " на той же колонке или EOF
    next_def = re.search(r"^\s*def\s+\w+\s*\(", txt[start:], re.M)
    body_end = start + (next_def.start() if next_def else len(txt) - start)
    body = txt[start:body_end]
    if "_imba_apply_env_overrides(config)" in body:
        return txt
    # ищем место вызова asyncio.run(run_...(config))
    pat_run = re.compile(rf"(^[ \t]*asyncio\.run\(\s*{re.escape(runner_call)}\s*\)\s*)", re.M)
    m2 = pat_run.search(body)
    if not m2:
        return txt
    insert_at = m2.start()
    # поднимемся до начала строки
    before = body[:insert_at]
    after  = body[insert_at:]
    indent = re.match(r"^[ \t]*", m2.group(1)).group(0)
    injection = f"{indent}try:\n{indent}    _imba_apply_env_overrides(config)\n{indent}except Exception:\n{indent}    pass\n"
    new_body = before + injection + after
    return txt[:start] + new_body + txt[body_end:]

def main():
    if not TARGET.exists():
        print(f"{WARN} {TARGET.name} not found — nothing to patch"); return
    src = TARGET.read_text(encoding="utf-8", errors="ignore")
    out = insert_helper(src)
    out2 = inject_call_before_asyncio(out, "paper", "run_paper_trading(config)")
    out3 = inject_call_before_asyncio(out2, "live",  "run_live_trading(config)")
    if out3 != src:
        bk = backup(TARGET, ".bak_cliupd_rescue")
        TARGET.write_text(out3, encoding="utf-8")
        print(f"{OK} Patched {TARGET.name} (env overrides injected){' (backup: '+bk+')' if bk else ''}")
    else:
        print(f"{OK} {TARGET.name} already contains env overrides")

if __name__ == "__main__":
    main()
