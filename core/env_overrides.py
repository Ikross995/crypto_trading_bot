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
