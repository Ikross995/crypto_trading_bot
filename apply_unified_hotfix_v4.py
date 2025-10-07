# apply_unified_hotfix_v4.py
from __future__ import annotations
from pathlib import Path
import re, shutil, os

BASE = Path(__file__).resolve().parent
OK="✅"; WARN="⚠️"

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
    print(f"{OK} {'Updated' if bk else 'Created'} {path.relative_to(BASE)}{f' (backup: {bk})' if bk else ''}")

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

# 1) core/env_overrides.py — надёжные оверрайды TESTNET/DRY_RUN (+ чтение .env.* вручную)
ENV_OVR = r'''
from __future__ import annotations
import os

def _truthy(v):
    if v is None: return None
    return str(v).strip().lower() in {"1","true","t","yes","y","on"}

def _read_env_file(path: str) -> dict:
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line=line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                k,v = line.split("=",1)
                out[k.strip()] = v.strip()
    except Exception:
        pass
    return out

def apply(config):
    # Базовые переменные окружения
    et = _truthy(os.getenv("TESTNET"))
    ed = _truthy(os.getenv("DRY_RUN"))
    if et is not None:
        try: config.testnet = bool(et)
        except Exception: pass
    if ed is not None:
        try: config.dry_run = bool(ed)
        except Exception: pass

    # Путь к .env из CLI/шима
    cfg_path = os.getenv("IMBA_CONFIG_PATH","")
    if isinstance(cfg_path, str) and cfg_path:
        # эвристика по имени файла
        if cfg_path.lower().endswith(".env.testnet"):
            try: config.testnet = True
            except Exception: pass
            # форсим через окружение для совместимости с клиентом
            os.environ.setdefault("IMBA_FORCE_TESTNET","1")
        # Парсим сам файл для TESTNET/DRY_RUN (если переменных в env ещё нет)
        file_vars = _read_env_file(cfg_path)
        if et is None and "TESTNET" in file_vars:
            try: config.testnet = _truthy(file_vars["TESTNET"]) or False
            except Exception: pass
            if _truthy(file_vars["TESTNET"]):
                os.environ.setdefault("IMBA_FORCE_TESTNET","1")
        if ed is None and "DRY_RUN" in file_vars:
            try: config.dry_run = _truthy(file_vars["DRY_RUN"]) or False
            except Exception: pass

    return config
'''.strip()

# 2) core/utils.py — validate_symbol / normalize_symbol стабы (мягко)
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

# 3) compat_complete.py — принудительное переключение клиента на testnet (idempotent)
def mutate_compat_complete(src: str):
    changed = False
    if "IMBA_FORCE_TESTNET_ENFORCER" in src:
        return src, changed
    append = r'''
# --- IMBA_FORCE_TESTNET_ENFORCER (idempotent) ---
try:
    import os as _imba_os
    import exchange.client as _imba_exclient
    _orig_init = getattr(_imba_exclient.BinanceClient, "__init__", None)
    if _orig_init and not getattr(_imba_exclient.BinanceClient, "_imba_force_testnet_patched", False):
        def _imba_init(self, *a, **k):
            _orig_init(self, *a, **k)
            tn = False
            # 1) config.testnet
            cfg = getattr(self, "config", None)
            if cfg is not None:
                try: tn = bool(getattr(cfg, "testnet", False))
                except Exception: tn = False
            # 2) env флаг
            if not tn:
                if str(_imba_os.getenv("IMBA_FORCE_TESTNET","")).lower() in {"1","true","t","yes","y","on"}:
                    tn = True
            # 3) путь к .env testnet
            if not tn:
                cp = str(_imba_os.getenv("IMBA_CONFIG_PATH",""))
                if cp.lower().endswith(".env.testnet"):
                    tn = True
            if tn:
                _url = "https://testnet.binancefuture.com"
                # попытки проставить базу на разных возможных объектах
                for attr in ("client","_client","um_futures","fapi","_http","_session","api"):
                    obj = getattr(self, attr, None)
                    if not obj: continue
                    for nm in ("base_url","_base_url","baseUrl","host"):
                        if hasattr(obj, nm):
                            try: setattr(obj, nm, _url)
                            except Exception: pass
                for nm in ("base_url","_base_url"):
                    if hasattr(self, nm):
                        try: setattr(self, nm, _url)
                        except Exception: pass
        _imba_exclient.BinanceClient.__init__ = _imba_init
        _imba_exclient.BinanceClient._imba_force_testnet_patched = True
except Exception:
    pass
# --- /IMBA_FORCE_TESTNET_ENFORCER ---
'''.lstrip("\n")
    src = src + "\n" + append
    changed = True
    return src, changed

# 4) runner/live.py — фикс self.getattr и безопасный min_account_balance + ранние оверрайды
def mutate_runner_live(src: str):
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
        lines[ins:ins] = ["from core.env_overrides import apply as _imba_apply_env_overrides\n", "import os as _imba_os\n"]
        src = "".join(lines); changed = True

    # ранний вызов в run_live_trading и live_trading_context
    def inject_in_def(txt: str, def_name: str):
        nonlocal changed
        pat = re.compile(rf"(^\s*async\s+def\s+{def_name}\s*\(\s*config\s*.*?\):\s*$)", re.M)
        m = pat.search(txt)
        if not m: return txt
        start = m.end()
        injection = "\n    try:\n        _imba_apply_env_overrides(config)\n    except Exception:\n        pass\n"
        if injection.strip() not in txt[start:start+300]:
            txt = txt[:start] + injection + txt[start:]
            changed = True
        return txt

    src = inject_in_def(src, "run_live_trading")
    src = inject_in_def(src, "live_trading_context")

    # в конструкторе LiveTradingEngine.__init__(self, config)
    pat_init = re.compile(r"(^\s*class\s+LiveTradingEngine\([^\)]*\):\s*.*?^(\s*)def\s+__init__\s*\(\s*self\s*,\s*config[^\)]*\)\s*:\s*$)", re.M|re.S)
    m = pat_init.search(src)
    if m:
        indent = m.group(2) or "    "
        insert_at = m.end()
        injection = f"\n{indent}    try:\n{indent}        _imba_apply_env_overrides(config)\n{indent}        self.config = config\n{indent}    except Exception:\n{indent}        pass\n"
        if injection.strip() not in src[insert_at:insert_at+400]:
            src = src[:insert_at] + injection + src[insert_at:]
            changed = True

    # безопасный доступ к min_account_balance
    new_src = re.sub(r"(?<!\w)self\.config\.min_account_balance(?!\w)", "getattr(self.config, 'min_account_balance', 0.0)", src)
    new_src = re.sub(r"(?<!\w)config\.min_account_balance(?!\w)", "getattr(config, 'min_account_balance', 0.0)", new_src)
    if new_src != src:
        src = new_src; changed = True

    # починка возможного self.getattr(...) → getattr(...)
    if "self.getattr(" in src:
        src = src.replace("self.getattr(", "getattr(")
        changed = True

    return src, changed

# 5) cli_integrated.py — ранний хук: IMBA_CONFIG_PATH из argv + IMBA_FORCE_TESTNET
def mutate_cli_integrated(src: str):
    changed = False

    if "from core.env_overrides import apply as _imba_apply_env_overrides" not in src:
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
        src = "".join(lines); changed = True

    # топ‑уровневый ранний хук (idempotent)
    if "IMBA_EARLY_CONFIG_HOOK" not in src:
        hook = r'''
# --- IMBA_EARLY_CONFIG_HOOK ---
try:
    import sys as _imba_sys, os as _imba_os
    # Подхват пути к .env из аргументов CLI
    for _a in reversed(_imba_sys.argv):
        if _a.endswith(".env") or _a.endswith(".env.testnet") or _a.endswith(".env.live"):
            _imba_os.environ.setdefault("IMBA_CONFIG_PATH", _a)
            if _a.lower().endswith(".env.testnet"):
                _imba_os.environ.setdefault("IMBA_FORCE_TESTNET","1")
            break
except Exception:
    pass
# --- /IMBA_EARLY_CONFIG_HOOK ---
'''.lstrip("\n")
        # вставим прямо после импортов/баннера
        lines = src.splitlines(True)
        ins = 0
        for i,l in enumerate(lines[:300]):
            ins = i+1
            if not l.strip().startswith(("import ","from ","#")) and l.strip():
                break
        src = "".join(lines[:ins] + [hook] + lines[ins:])
        changed = True

    # гарантированное применение оверрайдов внутри функций (если не вставлено ранее)
    def inject_call(txt: str, func_name: str):
        nonlocal changed
        pat = re.compile(rf"(^\s*def\s+{func_name}\s*\(.*?\):\s*$)", re.M)
        m = pat.search(txt)
        if not m: return txt
        start = m.end()
        call = "\n    try:\n        _imba_apply_env_overrides(config)\n    except Exception:\n        pass\n"
        if call.strip() not in txt[start:start+400]:
            txt = txt[:start] + call + txt[start:]
            changed = True
        return txt

    src = inject_call(src, "paper")
    src = inject_call(src, "live")

    return src, changed

def main():
    # 1) env_overrides
    write_file(BASE/"core"/"env_overrides.py", ENV_OVR, ".bak_envovr_v4")

    # 2) utils
    patch_text(BASE/"core"/"utils.py", mutate_utils, ".bak_utils_v4")

    # 3) compat_complete.py
    if (BASE/"compat_complete.py").exists():
        patch_text(BASE/"compat_complete.py", mutate_compat_complete, ".bak_cc_v4")
    else:
        print(f"{WARN} compat_complete.py not found — skip testnet enforcer")

    # 4) runner/live.py
    patch_text(BASE/"runner"/"live.py", mutate_runner_live, ".bak_live_v4")

    # 5) cli_integrated.py
    patch_text(BASE/"cli_integrated.py", mutate_cli_integrated, ".bak_cliint_v4")

    print("\nDone.")

if __name__ == "__main__":
    main()
