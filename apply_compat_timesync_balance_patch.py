# apply_compat_timesync_balance_patch.py
import re, shutil
from pathlib import Path

OK   = "\u2705"
WARN = "\u26A0\uFE0F"

BASE = Path(__file__).resolve().parent
TARGETS = [BASE/"compat_complete.py", BASE/"compat.py"]

BLOCK = r'''
# === COMPAT PATCH: BinanceClient.get_account_balance with time-sync & DRY_RUN stub (idempotent) ===
try:
    import os, time, hmac, hashlib, logging, requests, urllib.parse
    from core.config import get_config
    from exchange.client import BinanceClient
    _clog = logging.getLogger("compat")

    def _compat__ensure_time_offset_ms(base_url: str):
        try:
            r = requests.get(base_url + "/fapi/v1/time", timeout=5)
            js = r.json()
            st = int(js.get("serverTime"))
            off = st - int(time.time()*1000)
            return off
        except Exception as e:
            _clog.warning("compat: time sync failed: %s", e)
            return 0

    def _compat_get_account_balance(self):
        cfg = get_config()
        # DRY/PAPER: не ходим в сеть
        if getattr(cfg, "dry_run", False) or str(getattr(cfg, "mode", "")).lower() == "paper":
            return float(getattr(cfg, "paper_balance_usdt", 1000.0))

        api_key = getattr(self, "api_key", None) or os.getenv("BINANCE_API_KEY", "")
        api_secret = getattr(self, "api_secret", None) or os.getenv("BINANCE_API_SECRET", "")
        if not api_key or not api_secret:
            # нет ключей — безопасный дефолт
            return float(getattr(cfg, "paper_balance_usdt", 1000.0))

        base_url = "https://testnet.binancefuture.com" if getattr(cfg, "testnet", True) else "https://fapi.binance.com"
        recv_window = int(getattr(cfg, "recv_window_ms", 7000) or 7000)

        def _signed_params(params: dict) -> dict:
            # recvWindow ДО подписи (SAFE SIGNATURE PATCH)
            p = dict(params)
            p.setdefault("recvWindow", recv_window)
            q = urllib.parse.urlencode(p, doseq=True)
            sig = hmac.new(api_secret.encode("utf-8"), q.encode("utf-8"), hashlib.sha256).hexdigest()
            p["signature"] = sig
            return p

        # первичный timestamp c учётом (возможного) оффсета
        if not hasattr(self, "_time_offset_ms"):
            self._time_offset_ms = 0

        for attempt in (0, 1):
            ts = int(time.time()*1000) + int(getattr(self, "_time_offset_ms", 0))
            params = {"timestamp": ts}
            headers = {"X-MBX-APIKEY": api_key}
            try:
                r = requests.get(base_url + "/fapi/v2/balance", params=_signed_params(params), headers=headers, timeout=12)
                try:
                    data = r.json()
                except Exception:
                    data = {"status_code": r.status_code, "text": r.text}

                if r.ok:
                    bal = 0.0
                    if isinstance(data, list):
                        for b in data:
                            if str(b.get("asset","")).upper() == "USDT":
                                try: bal = float(b.get("balance", 0.0))
                                except Exception: bal = 0.0
                                break
                    return float(bal)

                # разбор ошибки (например, -1021/-1022)
                err_code = None
                if isinstance(data, dict):
                    err_code = data.get("code", None)
                if err_code in (-1021, -1022) and attempt == 0:
                    # Синхронизация времени + ретрай
                    self._time_offset_ms = _compat__ensure_time_offset_ms(base_url)
                    _clog.info("compat: synced futures time, offset=%sms", self._time_offset_ms)
                    continue

                raise RuntimeError(f"REST GET /fapi/v2/balance failed [{r.status_code}]: {data}")

            except Exception as e:
                if attempt == 0:
                    # ещё одна попытка после sync (вдруг это сетевой глич)
                    self._time_offset_ms = _compat__ensure_time_offset_ms(base_url)
                    _clog.info("compat: retrying balance after sync, offset=%sms", self._time_offset_ms)
                    continue
                raise

    # аккуратно дополним __init__, чтобы был _time_offset_ms
    try:
        _orig_init = BinanceClient.__init__
        def _patched_init(self, *a, **k):
            _orig_init(self, *a, **k)
            if not hasattr(self, "_time_offset_ms"):
                self._time_offset_ms = 0
        BinanceClient.__init__ = _patched_init
    except Exception as _e:
        _clog.debug("compat: __init__ patch skipped: %s", _e)

    # подключаем новую реализацию баланса
    try:
        BinanceClient.get_account_balance = _compat_get_account_balance
        _clog.info("compat: patched BinanceClient.get_account_balance (time-sync & DRY stub)")
    except Exception as _e:
        _clog.warning("compat: failed to patch get_account_balance: %s", _e)

except Exception as e:
    import logging
    logging.getLogger("compat").warning("compat patch (balance/timesync) failed: %s", e)
# === /COMPAT PATCH ===
'''

def backup(p: Path, suf=".bak_timesync"):
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + suf))

def patch_one(path: Path):
    if not path.exists():
        print(f"{WARN} {path.name} not found, skip")
        return
    src = path.read_text(encoding="utf-8", errors="ignore")
    if "COMPAT PATCH: BinanceClient.get_account_balance with time-sync" in src:
        print(f"{OK} {path.name} — patch already present")
        return
    # Вставим в конец файла (безопасно для compat-модуля)
    backup(path)
    path.write_text(src.rstrip() + "\n\n" + BLOCK.strip() + "\n", encoding="utf-8")
    print(f"{OK} Patched {path.name} (time-sync + DRY balance)")

def main():
    any_found = False
    for p in TARGETS:
        if p.exists():
            any_found = True
            patch_one(p)
    if not any_found:
        print(f"{WARN} compat file not found (looked for: {[t.name for t in TARGETS]})")
    else:
        print("\nDone.")

if __name__ == "__main__":
    main()
