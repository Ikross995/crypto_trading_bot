# -*- coding: utf-8 -*-
import os, re, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
LIVE = BASE / "runner" / "live.py"
SITE = BASE / "sitecustomize.py"
ORDERS_ADDON = BASE / "exchange" / "orders_cooldown_addon.py"

def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def write(p: Path, txt: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")

def backup(p: Path, suffix: str):
    b = p.with_name(p.name + suffix)
    try:
        if p.exists():
            b.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass

def patch_live_py():
    if not LIVE.exists():
        print(f"❌ {LIVE} not found")
        return False
    src = read(LIVE)
    original = src

    # 1) self.logger.info -> logger.info
    src = src.replace("self.logger.info(", "logger.info(")

    # 2) Безопасный min_account_balance
    src = re.sub(
        r"if\s+balance\s*<\s*self\.config\.min_account_balance\s*:",
        r"if balance < float(getattr(self.config, 'min_account_balance', 0.0) or 0.0):",
        src
    )

    # 3) Подмена вызова is_in_cooldown на безопасный враппер _is_in_cooldown
    src = src.replace(
        "if await self.order_manager.is_in_cooldown(signal.symbol):",
        "if await self._is_in_cooldown(signal.symbol):"
    )

    # 4) Вставка локального словаря кулдаунов в __init__
    if "_local_cooldowns" not in src:
        src = re.sub(
            r"(self\.processed_signals:.*?set\(\)\s*)",
            r"\1\n        # Local cooldown fallback\n        self._local_cooldowns: dict[str, float] = {}\n",
            src,
            flags=re.S
        )

    # 5) Вставить хелперы _note_cooldown и _is_in_cooldown внутрь класса до _can_trade_signal
    if "_is_in_cooldown(self" not in src:
        helper = '''
    def _note_cooldown(self, symbol: str) -> None:
        """Mark local/order-manager cooldown timestamp."""
        try:
            om = self.order_manager
            if hasattr(om, "note_cooldown"):
                om.note_cooldown(symbol)
            else:
                from datetime import datetime
                self._local_cooldowns[str(symbol).upper()] = datetime.utcnow().timestamp()
        except Exception:
            from datetime import datetime
            self._local_cooldowns[str(symbol).upper()] = datetime.utcnow().timestamp()

    async def _is_in_cooldown(self, symbol: str) -> bool:
        """Return True if we are inside the cooldown window for the symbol."""
        try:
            om = self.order_manager
            if hasattr(om, "is_in_cooldown"):
                res = om.is_in_cooldown(symbol)
                import asyncio
                return await res if asyncio.iscoroutine(res) else bool(res)
        except Exception:
            pass
        from datetime import datetime
        last = float(self._local_cooldowns.get(str(symbol).upper(), 0.0) or 0.0)
        cd = float(getattr(self.config, "cooldown_sec", 60) or 60.0)
        return (datetime.utcnow().timestamp() - last) < cd

'''
        # Вставим перед async def _can_trade_signal
        src = re.sub(r"(\n\s+async\s+def\s+_can_trade_signal)", helper + r"\1", src)

    # 6) После удачного размещения ордера отмечаем кулдаун
    if "self._note_cooldown(symbol)" not in src:
        src = re.sub(
            r'(logger\.info\(f"Order placed:.*?\)\s*\)\s*)',
            r'\1\n                # mark cooldown\n                self._note_cooldown(symbol)\n',
            src,
            flags=re.S
        )

    if src != original:
        backup(LIVE, ".bak_live_cdfix")
        write(LIVE, src)
        print("✅ Patched runner\\live.py (cooldown fallback, logger fix, safe min_account_balance)")
        return True
    else:
        print("ℹ️ runner\\live.py already patched / no changes needed")
        return True

def write_orders_addon():
    code = r'''# -*- coding: utf-8 -*-
"""
orders_cooldown_addon: adds soft cooldown helpers into exchange.orders.OrderManager

- is_in_cooldown(symbol) -> bool
- note_cooldown(symbol) -> None
- wraps place_order() to record cooldown timestamp automatically
"""
import time, asyncio, inspect, logging

log = logging.getLogger("orders_addon")

try:
    from exchange.orders import OrderManager
except Exception as e:
    print("orders_addon: cannot import OrderManager:", e)
    OrderManager = None

if OrderManager is not None:
    # class-level store (simple & cross-instances)
    if not hasattr(OrderManager, "_cooldowns"):
        OrderManager._cooldowns = {}

    if not hasattr(OrderManager, "cooldown_sec"):
        # default fallback; engine may still use its own local cooldown with config.cooldown_sec
        OrderManager.cooldown_sec = 60

    def _note_cd(self, symbol: str):
        try:
            if symbol:
                OrderManager._cooldowns[str(symbol).upper()] = time.time()
        except Exception:
            pass

    def note_cooldown(self, symbol: str):
        _note_cd(self, symbol)

    def is_in_cooldown(self, symbol: str):
        if not symbol:
            return False
        try:
            cd = float(getattr(self, "cooldown_sec", 60) or 60.0)
        except Exception:
            cd = 60.0
        last = float(OrderManager._cooldowns.get(str(symbol).upper(), 0.0) or 0.0)
        return (time.time() - last) < cd

    if not hasattr(OrderManager, "note_cooldown"):
        setattr(OrderManager, "note_cooldown", note_cooldown)
    if not hasattr(OrderManager, "is_in_cooldown"):
        setattr(OrderManager, "is_in_cooldown", is_in_cooldown)

    # wrap place_order to mark cooldown after success
    try:
        _orig_place = getattr(OrderManager, "place_order", None)
        if _orig_place is not None and not getattr(OrderManager, "_cd_wrapped", False):
            if asyncio.iscoroutinefunction(_orig_place):
                async def _place_wrap_async(self, *a, **k):
                    res = await _orig_place(self, *a, **k)
                    sym = k.get("symbol")
                    if not sym and hasattr(res, "symbol"):
                        sym = res.symbol
                    _note_cd(self, sym)
                    return res
                OrderManager.place_order = _place_wrap_async
            else:
                def _place_wrap_sync(self, *a, **k):
                    res = _orig_place(self, *a, **k)
                    sym = k.get("symbol")
                    if not sym and hasattr(res, "symbol"):
                        sym = res.symbol
                    _note_cd(self, sym)
                    return res
                OrderManager.place_order = _place_wrap_sync
            OrderManager._cd_wrapped = True
            log.info("orders_addon: cooldown wrapper installed")
    except Exception as e:
        log.warning("orders_addon: failed to wrap place_order: %s", e)
'''
    backup(ORDERS_ADDON, ".bak_orders_cd_addon")
    write(ORDERS_ADDON, code)
    print("✅ Created/updated exchange\\orders_cooldown_addon.py")
    return True

def patch_sitecustomize():
    line = "import exchange.orders_cooldown_addon  # cooldown addon"
    if not SITE.exists():
        write(SITE, f"# auto-created by patcher\ntry:\n    {line}\nexcept Exception as e:\n    print('sitecustomize: orders_addon failed:', e)\n")
        print(f"✅ Created {SITE.name} with orders cooldown import")
        return True
    txt = read(SITE)
    if "orders_cooldown_addon" in txt:
        print("ℹ️ sitecustomize.py already imports orders_cooldown_addon")
        return True
    txt += f"\ntry:\n    {line}\nexcept Exception as e:\n    print('sitecustomize: orders_addon failed:', e)\n"
    backup(SITE, ".bak_site_cd")
    write(SITE, txt)
    print("✅ Patched sitecustomize.py (import orders cooldown addon)")
    return True

def main():
    ok1 = patch_live_py()
    ok2 = write_orders_addon()
    ok3 = patch_sitecustomize()
    print("\nSummary:")
    print(f"  live.py patched:        {ok1}")
    print(f"  orders_cooldown_addon:  {ok2}")
    print(f"  sitecustomize.py:       {ok3}")
    print("\nDone.")

if __name__ == "__main__":
    main()
