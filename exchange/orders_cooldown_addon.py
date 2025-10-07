# -*- coding: utf-8 -*-
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
