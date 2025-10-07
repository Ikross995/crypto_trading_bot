# apply_unified_live_fix_v2.py
from __future__ import annotations
import re, shutil, sys, os
from pathlib import Path

OK="✅"; WARN="⚠️"; INFO="ℹ️"
BASE = Path(__file__).resolve().parent

def backup(p: Path, suf: str):
    if p.exists():
        bk = p.with_suffix(p.suffix + suf)
        shutil.copy2(p, bk)
        return bk.name
    return None

def write_file(p: Path, content: str, bak_suffix: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    bk = backup(p, bak_suffix)
    p.write_text(content.rstrip()+"\n", encoding="utf-8")
    if bk: print(f"{OK} Updated {p.relative_to(BASE)} (backup: {bk})")
    else:  print(f"{OK} Created {p.relative_to(BASE)}")

# 1) sitecustomize.py — ранняя подгрузка .env + validate_symbol stub
SITE_PATH = BASE/"sitecustomize.py"
SITE_PAYLOAD = r'''
# sitecustomize — IMBA unified live fixes
import os, sys, builtins

# 1) Глобальные гварды (на всякий случай)
for _nm in ("sig","signal","trade_signal"):
    if not hasattr(builtins, _nm):
        setattr(builtins, _nm, None)

# 2) Перехват --config и ранняя загрузка .env
def _imba_grab_config(argv):
    p = os.environ.get("IMBA_CONFIG_PATH", "")
    if p: return p, argv
    if "--config" in argv:
        try:
            i = argv.index("--config")
            if i+1 < len(argv):
                p = argv[i+1]
                os.environ["IMBA_CONFIG_PATH"] = p
                del argv[i:i+2]
                print(f"✅ sitecustomize: IMBA_CONFIG_PATH={p}")
        except Exception:
            pass
    return os.environ.get("IMBA_CONFIG_PATH",""), argv

def _imba_load_env(path):
    if not path: return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=True)
        print(f"✅ sitecustomize: loaded .env from {path}")
    except Exception as e:
        print(f"⚠️ sitecustomize: dotenv load failed: {e}")

_cfg, _argv = _imba_grab_config(sys.argv)
_imba_load_env(_cfg)
sys.argv = _argv

# 3) validate_symbol stub (до compat)
try:
    import importlib, types
    cu = importlib.import_module("core.utils")
    if not hasattr(cu, "validate_symbol"):
        def validate_symbol(sym: str) -> str:
            try: s = str(sym).strip().upper()
            except Exception: s = ""
            return s
        setattr(cu, "validate_symbol", validate_symbol)
        print("✅ sitecustomize: core.utils.validate_symbol stub injected")
    if not hasattr(cu, "normalize_symbol"):
        def normalize_symbol(sym: str) -> str:
            return cu.validate_symbol(sym)
        setattr(cu, "normalize_symbol", normalize_symbol)
except Exception as e:
    print(f"⚠️ sitecustomize: validate_symbol stub failed: {e}")
'''.strip()

# 2) compat_complete.py — вырезать рекурсивные _patched_init и вставить безопасный патч __init__
COMPAT_PATHS = [BASE/"compat_complete.py", BASE/"compat.py"]
SAFE_INIT_BLOCK = r'''
# --- IMBA SAFE INIT PATCH (idempotent, anti-recursion) ---
try:
    import logging, importlib
    _lg = logging.getLogger("compat")
    _mod = importlib.import_module("exchange.client")
    _B = getattr(_mod, "BinanceClient", None)
    if _B is not None:
        # Удаляем прежние рекурсивные обёртки: заменяем __init__ на безопасную,
        # где "оригинал" определяется как __imba_orig_init__ или текущий __init__ без повторной ребайндной цепочки.
        _orig = getattr(_B.__init__, "__imba_orig_init__", _B.__init__)
        def __imba_init__(self, *a, **k):
            # Если уже есть "настоящий" original — вызываем его; иначе просто исполняем как есть
            return _orig(self, *a, **k)
        __imba_init__.__imba_orig_init__ = _orig
        if not getattr(_B, "__imba_init_patched__", False) or getattr(_B.__init__, "__name__", "") != "__imba_init__":
            _B.__init__ = __imba_init__
            _B.__imba_init_patched__ = True
            _lg.info("compat: BinanceClient.__init__ patched safely (idempotent)")
        else:
            _lg.info("compat: BinanceClient.__init__ already safe")
except Exception as _e:
    import logging
    logging.getLogger("compat").warning("compat: SAFE INIT PATCH failed: %s", _e)
'''.strip()

def patch_compat():
    for p in COMPAT_PATHS:
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        changed = False

        # вырежем все блоки вида: def _patched_init(...) ... BinanceClient.__init__ = _patched_init
        pat = re.compile(r"def\s+_patched_init\s*\(.*?\):.*?BinanceClient\s*\.\s*__init__\s*=\s*_patched_init", re.S)
        if pat.search(txt):
            txt = pat.sub("# -- removed recursive _patched_init --", txt)
            changed = True

        # вставим наш безопасный блок, если его ещё нет
        if "IMBA SAFE INIT PATCH" not in txt:
            txt = txt.rstrip() + "\n\n" + SAFE_INIT_BLOCK + "\n"
            changed = True

        if changed:
            bk = backup(p, ".bak_livefix")
            p.write_text(txt, encoding="utf-8")
            print(f"{OK} Patched {p.relative_to(BASE)} (safe __init__ + removed recursive)")
        else:
            print(f"{OK} {p.relative_to(BASE)} already safe")

# 3) cli_integrated.py / cli_updated.py — уважаем TESTNET/DRY_RUN из .env
CLI_HELPER = r'''
# --- IMBA: apply env overrides for TESTNET/DRY_RUN (idempotent) ---
def _imba_env_bool(name: str):
    v = os.getenv(name, None)
    if v is None: return None
    return str(v).strip().lower() in {"1","true","t","yes","y","on"}

def _imba_apply_env_overrides(cfg):
    try:
        et = _imba_env_bool("TESTNET")
        ed = _imba_env_bool("DRY_RUN")
        # если пользователь явно не передал флаг, уважаем .env
        if et is not None:
            cfg.testnet = bool(et)
        if ed is not None:
            cfg.dry_run = bool(ed)
    except Exception:
        pass
'''.strip()

def patch_cli_one(path: Path):
    if not path.exists():
        print(f"{WARN} {path.name} not found — skip"); return
    src = path.read_text(encoding="utf-8", errors="ignore")
    out = src
    changed = False

    # вставим helper после импортов
    if "_imba_apply_env_overrides(" not in out:
        lines = out.splitlines(True)
        ins = 0
        for i,l in enumerate(lines[:200]):
            if l.strip().startswith(("import ","from ")):
                ins = i+1
            elif l.strip()=="" or l.strip().startswith(("#","'''",'"""')): 
                continue
            else:
                break
        lines[ins:ins] = [CLI_HELPER+"\n\n"]
        out = "".join(lines)
        changed = True

    # вставим вызовы в функции paper/live: найдём места, где есть run_..._trading(config)
    def inject_call(txt: str, func_name: str, runner_call: str) -> str:
        pat = re.compile(rf"(def\s+{func_name}\s*\(.*?\)\s*:\s*\n(?:.*\n)+?)(\s*asyncio\.run\(\s*{re.escape(runner_call)}\s*\)\s*)", re.S)
        m = pat.search(txt)
        if not m:
            return txt
        head, tail = m.group(1), m.group(2)
        if "_imba_apply_env_overrides(config)" in head:
            return txt
        head2 = head + "    try:\n        _imba_apply_env_overrides(config)\n    except Exception:\n        pass\n"
        return txt.replace(m.group(0), head2 + tail)

    out2 = inject_call(out, "paper", "run_paper_trading(config)")
    out3 = inject_call(out2, "live",  "run_live_trading(config)")
    if out3 != src:
        bk = backup(path, ".bak_envcli")
        path.write_text(out3, encoding="utf-8")
        print(f"{OK} Patched {path.name} (env overrides){' (backup: '+bk+')' if bk else ''}")
    else:
        print(f"{OK} {path.name} already has env overrides")

def patch_cli():
    for name in ("cli_integrated.py", "cli_updated.py"):
        patch_cli_one(BASE/name)

def main():
    # 1) sitecustomize (ранний stub + .env loader)
    write_file(SITE_PATH, SITE_PAYLOAD, ".bak_sitev2")
    # 2) compat (безопасный __init__)
    patch_compat()
    # 3) CLI (уважаем TESTNET/DRY_RUN из .env)
    patch_cli()
    print("\nDone.")

if __name__ == "__main__":
    main()
