# -*- coding: utf-8 -*-
"""
Единый мастер‑патч для проекта crypto_trading_bot:
- Исправляет 'self.getattr' в runner/live.py -> безопасный getattr(self.config, ...)
- Вшивает env-overrides (TESTNET/DRY_RUN/MIN_ACCOUNT_BALANCE/IMBA_RECV_WINDOW_MS/ALLOW_TIME_DRIFT_MS)
- Добавляет core.utils.validate_symbol, если отсутствует
- Подключает env_overrides в LiveTradingEngine.__init__ (безопасно, идемпотентно)
Автор: unified patch v5
"""

from __future__ import annotations
import os, re, sys, io
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
BASE = ROOT  # текущая директория — у вас это .../crypto_trading_bot/work
# Для большинства раскладок файлы есть именно тут:
P_CORE = BASE / "core"
P_RUNNER = BASE / "runner"
P_EXCH = BASE / "exchange"

def backup(path: Path):
    if not path.exists():
        return
    bak = path.with_suffix(path.suffix + ".bak_unified_v5")
    if not bak.exists():
        bak.write_bytes(path.read_bytes())

def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def patch_env_overrides():
    """Создаёт/обновляет core/env_overrides.py — единое место для гибких оверрайдов из .env."""
    path = P_CORE / "env_overrides.py"
    backup(path)
    code = dedent(r'''
        # -*- coding: utf-8 -*-
        """
        Env overrides (универсальные):
        - .env подхватывается из BOT_CONFIG_PATH, CONFIG_PATH или аргумента функции
        - переносит TESTNET/DRY_RUN/MIN_ACCOUNT_BALANCE/IMBA_RECV_WINDOW_MS/ALLOW_TIME_DRIFT_MS в объект config
        """
        from __future__ import annotations
        import os
        from typing import Optional

        def _b(v) -> bool:
            return str(v).strip().lower() in {"1","true","t","yes","y","on"}

        def _f(v, default=0.0) -> float:
            try:
                return float(v)
            except Exception:
                return default

        def apply_default_overrides(config, explicit_env_path: Optional[str] = None):
            # 1) Подгружаем .env, если указан путь
            env_path = explicit_env_path or os.getenv("BOT_CONFIG_PATH") or os.getenv("CONFIG_PATH")
            try:
                from dotenv import load_dotenv
            except Exception:
                load_dotenv = None

            if env_path and load_dotenv:
                try:
                    load_dotenv(env_path, override=True)
                except Exception:
                    pass

            # 2) Применяем TESTNET/DRY_RUN при наличии в окружении
            tv = os.getenv("TESTNET")
            dv = os.getenv("DRY_RUN")
            if tv is not None:
                try: setattr(config, "testnet", _b(tv))
                except Exception: pass
            if dv is not None:
                try: setattr(config, "dry_run", _b(dv))
                except Exception: pass

            # 3) MIN_ACCOUNT_BALANCE
            if not hasattr(config, "min_account_balance"):
                try:
                    setattr(config, "min_account_balance", _f(os.getenv("MIN_ACCOUNT_BALANCE", 0.0), 0.0))
                except Exception:
                    pass
            else:
                v = os.getenv("MIN_ACCOUNT_BALANCE")
                if v is not None:
                    try:
                        config.min_account_balance = _f(v, config.min_account_balance)
                    except Exception:
                        pass

            # 4) Окно подписи recvWindow (мс)
            if not hasattr(config, "recv_window_ms"):
                try:
                    setattr(config, "recv_window_ms", int(float(os.getenv("IMBA_RECV_WINDOW_MS", "7000"))))
                except Exception:
                    pass

            # 5) Допустимый дрейф времени (мс) — может использоваться в client.safe_call
            if not hasattr(config, "allow_time_drift_ms"):
                try:
                    setattr(config, "allow_time_drift_ms", int(float(os.getenv("ALLOW_TIME_DRIFT_MS", "2000"))))
                except Exception:
                    pass
    ''').strip() + "\n"
    write_text(path, code)
    return path

def patch_core_utils():
    """Добавляет validate_symbol, если его нет, чтобы не падали сторонние патчи."""
    path = P_CORE / "utils.py"
    if not path.exists():
        return None, "core/utils.py not found (skip, не критично)"
    backup(path)
    txt = path.read_text(encoding="utf-8")

    if "def validate_symbol(" in txt:
        return path, "validate_symbol already present"

    # Вставим в конец файла простую безопасную реализацию
    addition = dedent(r'''
        # --- unified patch v5: safe validate_symbol ---
        def validate_symbol(symbol: str) -> str:
            """
            Безопасная нормализация торгового символа (очень либеральная).
            Нужна для обратной совместимости совместимых патчей.
            """
            if not isinstance(symbol, str):
                symbol = str(symbol or "")
            s = symbol.strip().upper()
            # Не навязываем USDT-хвост, только нормализуем регистр/пробелы.
            return s
    ''').strip() + "\n"
    out = txt.rstrip() + "\n\n" + addition
    write_text(path, out)
    return path, "validate_symbol added"

def _inject_import_env_overrides(live_txt: str) -> str:
    """Гарантированно импортирует apply_default_overrides в runner/live.py (один раз)."""
    if "from core.env_overrides import apply_default_overrides" in live_txt:
        return live_txt
    # Найдём блок импортов и вставим
    lines = live_txt.splitlines()
    insert_at = 0
    for i, L in enumerate(lines[:80]):  # только в верхней части файла
        if L.startswith("import ") or L.startswith("from "):
            insert_at = i + 1
    lines.insert(insert_at, "from core.env_overrides import apply_default_overrides as _cfg_apply_overrides")
    return "\n".join(lines)

def _inject_call_env_overrides_in_init(live_txt: str) -> str:
    """
    В конструктор LiveTradingEngine.__init__(..., config) вставляем вызов _cfg_apply_overrides(config).
    Делаем это идемпотентно.
    """
    if "_cfg_apply_overrides(config)" in live_txt:
        return live_txt

    pat = re.compile(r"(class\s+LiveTradingEngine\s*\(.*?\):.*?def\s+__init__\s*\(\s*self\s*,\s*config[^\)]*\)\s*:\s*)([\s\S]*?)(\n\s*def\s+)", re.M)
    m = pat.search(live_txt)
    if not m:
        # резервный паттерн попроще
        pat2 = re.compile(r"(def\s+__init__\s*\(\s*self\s*,\s*config[^\)]*\)\s*:\s*)([\s\S]*?)(\n\s*def\s+)", re.M)
        m = pat2.search(live_txt)

    if not m:
        return live_txt  # не нашли — не ломаем файл

    head, body, nextdef = m.groups()
    # определим отступ тела
    indent = ""
    for line in body.splitlines():
        if line.strip():
            indent = line[:len(line) - len(line.lstrip())]
            break
    inject_line = f"\n{indent}_cfg_apply_overrides(config)\n"
    new_body = body + inject_line
    out = live_txt[:m.start(2)] + new_body + live_txt[m.end(2):]
    return out

def _fix_self_getattr_and_config(live_txt: str) -> str:
    """
    Лечим код вида:
      if balance < self.getattr(config, 'min_account_balance', 0.0):
    -> if balance < getattr(self.config, 'min_account_balance', 0.0):

    Плюс безопасно заменяем любые 'self.getattr(' -> 'getattr('
    """
    # 1) Точный кейс:
    live_txt = re.sub(
        r"self\.getattr\s*\(\s*config\s*,\s*(['\"])min_account_balance\1\s*,\s*([^)]+)\)",
        r"getattr(self.config, 'min_account_balance', \2)",
        live_txt
    )
    # 2) Общее: self.getattr( -> getattr(
    live_txt = re.sub(r"self\.getattr\s*\(", "getattr(", live_txt)

    # 3) Случаи, где написали getattr(config, ...) вместо getattr(self.config, ...)
    live_txt = re.sub(
        r"getattr\s*\(\s*config\s*,",
        r"getattr(self.config,",
        live_txt
    )
    return live_txt

def patch_runner_live():
    path = P_RUNNER / "live.py"
    if not path.exists():
        return None, "runner/live.py not found"
    backup(path)
    txt = path.read_text(encoding="utf-8")
    orig = txt

    txt = _inject_import_env_overrides(txt)
    txt = _inject_call_env_overrides_in_init(txt)
    txt = _fix_self_getattr_and_config(txt)

    if txt != orig:
        write_text(path, txt)
        return path, "live.py patched (env overrides + getattr fix)"
    return path, "live.py already OK"

def main():
    changed = []

    # 1) env_overrides (создание/обновление)
    p = patch_env_overrides()
    changed.append(f"✓ updated {p.relative_to(BASE)}")

    # 2) utils: validate_symbol
    p, msg = patch_core_utils()
    if p:
        changed.append(f"✓ patched {p.relative_to(BASE)} — {msg}")
    else:
        changed.append(f"• {msg}")

    # 3) runner/live.py: импорт и вызов env_overrides, fix getattr
    p, msg = patch_runner_live()
    if p:
        changed.append(f"✓ patched {p.relative_to(BASE)} — {msg}")
    else:
        changed.append(f"• {msg}")

    print("\nSummary:")
    for line in changed:
        print(" ", line)
    print("\nDone.")

if __name__ == "__main__":
    main()
