# apply_final_unified_patch_v3.py
from __future__ import annotations
from pathlib import Path
import re, shutil, os

BASE = Path(__file__).resolve().parent
OK="✅"; WARN="⚠️"; INFO="ℹ️"

def backup(p: Path, suf: str):
    if p.exists():
        bk = p.with_suffix(p.suffix + suf)
        shutil.copy2(p, bk)
        return bk.name
    return ""

def write_file(path: Path, content: str, bak_suffix: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    bk = backup(path, bak_suffix)
    path.write_text(content.rstrip()+"\n", encoding="utf-8")
    if bk:
        print(f"{OK} Updated {path.relative_to(BASE)} (backup: {bk})")
    else:
        print(f"{OK} Created {path.relative_to(BASE)}")

def patch_text(path: Path, mutate, bak_suffix: str):
    if not path.exists():
        print(f"{WARN} {path.relative_to(BASE)} not found — skip")
        return False
    src = path.read_text(encoding="utf-8", errors="ignore")
    out, changed = mutate(src)
    if changed:
        bk = backup(path, bak_suffix)
        path.write_text(out, encoding="utf-8")
        print(f"{OK} Patched {path.relative_to(BASE)}{f' (backup: {bk})' if bk else ''}")
    else:
        print(f"{OK} {path.relative_to(BASE)} already OK")
    return changed

# 1) core/env_overrides.py — единая точка оверрайдов TESTNET/DRY_RUN
ENV_OVR = r'''
# core/env_overrides.py — centralized TESTNET/DRY_RUN overrides
from __future__ import annotations
import os

def _truthy(v):
    if v is None: return None
    return str(v).strip().lower() in {"1","true","t","yes","y","on"}

def apply(config):
    # .env overrides
    et = _truthy(os.getenv("TESTNET"))
    ed = _truthy(os.getenv("DRY_RUN"))
    if et is not None:
        try: config.testnet = bool(et)
        except Exception: pass
    if ed is not None:
        try: config.dry_run = bool(ed)
        except Exception: pass
    # Heuristic: путь .env.testnet => testnet True
    cfg_path = os.getenv("IMBA_CONFIG_PATH","")
    if isinstance(cfg_path, str) and cfg_path.lower().endswith(".env.testnet"):
        try: config.testnet = True
        except Exception: pass
    return config
'''.strip()

# 2) core/utils.py — validate_symbol / normalize_symbol стабы (идемпотентно)
def mutate_utils(src: str):
    changed = False
    if "def validate_symbol(" not in src:
        src += "\n\ndef validate_symbol(sym: str) -> str:\n"
        src += "    try:\n        return str(sym).strip().upper()\n"
        src += "    except Exception:\n        return \"\"\n"
        changed = True
    if "def normalize_symbol(" not in src:
        src += "\n\ndef normalize_symbol(sym: str) -> str:\n"
        src += "    return validate_symbol(sym)\n"
        changed = True
    return src, changed

# 3) compat_complete.py — безопасный импорт validate_symbol
def mutate_compat_complete(src: str):
    changed = False
    if "from core.utils import validate_symbol" in src and "IMBA_SAFE_VALIDATE_IMPORT" not in src:
        src = src.replace(
            "from core.utils import validate_symbol",
            "# IMBA_SAFE_VALIDATE_IMPORT\ntry:\n    from core.utils import validate_symbol\nexcept Exception:\n    def validate_symbol(s: str) -> str:\n        try: return str(s).strip().upper()\n        except Exception: return \"\"\n"
        )
        changed = True
    return src, changed

# 4) runner/live.py — ранний apply(env overrides) + guard min_account_balance
def mutate_runner_live(src: str):
    changed = False
    # импорт helper
    if "from core.env_overrides import apply as _imba_apply_env_overrides" not in src:
        # вставим после верхних импортов
        lines = src.splitlines(True)
        ins = 0
        for i,l in enumerate(lines[:300]):
            if l.strip().startswith(("import ","from ")):
                ins = i+1
            elif l.strip()=="" or l.strip().startswith(("#","'''",'\"\"\"')):
                continue
            else:
                break
        lines[ins:ins] = ["from core.env_overrides import apply as _imba_apply_env_overrides\n"]
        src = "".join(lines)
        changed = True

    # инъекция в run_live_trading(config)
    def inject_in_def(txt: str, def_name: str):
        nonlocal changed
        pat = re.compile(rf"(^\s*async\s+def\s+{def_name}\s*\(\s*config\s*.*?\):\s*$)", re.M)
        m = pat.search(txt)
        if not m: return txt
        start = m.end()
        # найдём позицию для вставки (после докстринга/пустых строк)
        body = txt[start:]
        # вставим сразу в начало тела
        injection = "\n    try:\n        _imba_apply_env_overrides(config)\n    except Exception:\n        pass\n"
        if injection.strip() not in body[:300]:
            txt = txt[:start] + injection + body
            changed = True
        return txt

    src = inject_in_def(src, "run_live_trading")
    src = inject_in_def(src, "live_trading_context")

    # инъекция в конструктор LiveTradingEngine.__init__(self, config)
    pat_init = re.compile(r"(^\s*class\s+LiveTradingEngine\([^\)]*\):\s*.*?^(\s*)def\s+__init__\s*\(\s*self\s*,\s*config[^\)]*\)\s*:\s*$)", re.M|re.S)
    m = pat_init.search(src)
    if m:
        indent = m.group(2) or "    "
        insert_at = m.end()
        injection = f"\n{indent}    try:\n{indent}        _imba_apply_env_overrides(config)\n{indent}        self.config = config\n{indent}    except Exception:\n{indent}        pass\n"
        if injection.strip() not in src[insert_at:insert_at+400]:
            src = src[:insert_at] + injection + src[insert_at:]
            changed = True

    # guard для min_account_balance
    rep1 = re.sub(r"(?<!\w)config\.min_account_balance(?!\w)", "getattr(config, 'min_account_balance', 0.0)", src)
    rep2 = re.sub(r"(?<!\w)self\.config\.min_account_balance(?!\w)", "getattr(self.config, 'min_account_balance', 0.0)", rep1)
    if rep2 != src:
        src = rep2
        changed = True
    return src, changed

# 5) cli_integrated.py — применить env overrides ДО печати таблицы/стартов
def mutate_cli_integrated(src: str):
    changed = False
    if "from core.env_overrides import apply as _imba_apply_env_overrides" not in src:
        # вставим после импортов
        lines = src.splitlines(True)
        ins = 0
        for i,l in enumerate(lines[:300]):
            if l.strip().startswith(("import ","from ")):
                ins = i+1
            elif l.strip()=="" or l.strip().startswith(("#","'''",'\"\"\"')):
                continue
            else:
                break
        lines[ins:ins] = ["from core.env_overrides import apply as _imba_apply_env_overrides\n"]
        src = "".join(lines)
        changed = True

    def inject_call(txt: str, func_name: str):
        nonlocal changed
        # найдём начало def ... (версия с Typer/Click)
        pat = re.compile(rf"(^\s*def\s+{func_name}\s*\(.*?\):\s*$)", re.M)
        m = pat.search(txt)
        if not m: return txt
        start = m.end()
        body = txt[start:]
        injection = "\n    try:\n        _imba_apply_env_overrides(config)\n    except Exception:\n        pass\n"
        # вставлять будем перед первой печатью/шапкой, но без тяжёлых регексов — просто в начало тела
        if injection.strip() not in body[:400]:
            txt = txt[:start] + injection + body
            changed = True
        return txt

    src = inject_call(src, "paper")
    src = inject_call(src, "live")
    return src, changed

def main():
    # 1) core/env_overrides.py
    write_file(BASE/"core"/"env_overrides.py", ENV_OVR, ".bak_envovr")

    # 2) core/utils.py
    patch_text(BASE/"core"/"utils.py", mutate_utils, ".bak_utils_v3")

    # 3) compat_complete.py (если есть)
    if (BASE/"compat_complete.py").exists():
        patch_text(BASE/"compat_complete.py", mutate_compat_complete, ".bak_cc_v3")
    else:
        print(f"{WARN} compat_complete.py not found — skip import guard")

    # 4) runner/live.py
    patch_text(BASE/"runner"/"live.py", mutate_runner_live, ".bak_live_v3")

    # 5) cli_integrated.py
    patch_text(BASE/"cli_integrated.py", mutate_cli_integrated, ".bak_cliint_v3")

    print("\nDone.")

if __name__ == "__main__":
    main()
