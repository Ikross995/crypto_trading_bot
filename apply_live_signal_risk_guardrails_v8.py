# apply_live_signal_risk_guardrails_v8.py
# -*- coding: utf-8 -*-
import re, sys, shutil
from pathlib import Path

LIVE_PATH = Path("runner") / "live.py"

NEW_BODY = r'''
        """
        Process one complete trading cycle (v8 guardrails):
        - normalize signals (accept dicts/objects; map id/signal_id)
        - call generate_signal with keyword (symbol=...)
        - coerce position size to float (handle tuples)
        - optional cooldown check if method exists
        """
        import time
        from datetime import datetime

        async def _v8_gen(symbol):
            # Prefer keyword; fallback to positional for legacy signatures
            try:
                return await self.signal_generator.generate_signal(symbol=symbol)
            except TypeError:
                try:
                    return await self.signal_generator.generate_signal(symbol)
                except TypeError:
                    return None

        def _v8_norm_signal(s, default_symbol):
            # Return a simple object with required attributes or None
            class _NSig:
                __slots__ = ("symbol","side","strength","id","timestamp","entry_price","reason","confidence")
                def __init__(self, **kw):
                    for k in self.__slots__:
                        setattr(self, k, kw.get(k))
            if s is None:
                return None
            # dict-like
            if isinstance(s, dict):
                sym = s.get("symbol") or default_symbol
                side = s.get("side") or s.get("signal_type")
                strength = s.get("strength", s.get("confidence", 0.0)) or 0.0
                try:
                    strength = float(strength)
                except Exception:
                    strength = 0.0
                sid = s.get("id") or s.get("signal_id") or f"{sym}-{(side or 'NA')}-{int(time.time()*1000)}"
                ts = s.get("timestamp") or datetime.utcnow()
                entry = s.get("entry_price") or s.get("price")
                reason = s.get("reason")
                conf = s.get("confidence", strength) or 0.0
                try:
                    conf = float(conf)
                except Exception:
                    conf = strength
                try:
                    side_u = str(side).upper() if side is not None else None
                except Exception:
                    side_u = None
                return _NSig(symbol=str(sym), side=side_u, strength=float(strength),
                             id=sid, timestamp=ts, entry_price=entry,
                             reason=reason, confidence=conf)
            # object-like
            try:
                sym = getattr(s, "symbol", default_symbol)
                side = getattr(s, "side", None)
                strength = getattr(s, "strength", getattr(s, "confidence", 0.0)) or 0.0
                try:
                    strength = float(strength)
                except Exception:
                    strength = 0.0
                sid = getattr(s, "id", None) or getattr(s, "signal_id", None) or f"{sym}-{(side or 'NA')}-{int(time.time()*1000)}"
                ts = getattr(s, "timestamp", datetime.utcnow())
                entry = getattr(s, "entry_price", getattr(s, "price", None))
                reason = getattr(s, "reason", None)
                conf = getattr(s, "confidence", strength) or 0.0
                try:
                    conf = float(conf)
                except Exception:
                    conf = strength
                try:
                    side_u = str(side).upper() if side is not None else None
                except Exception:
                    side_u = None
                return _NSig(symbol=str(sym), side=side_u, strength=float(strength),
                             id=sid, timestamp=ts, entry_price=entry,
                             reason=reason, confidence=conf)
            except Exception:
                return None

        def _v8_coerce_size(x):
            try:
                # Risk manager may return tuple (qty, meta)
                if isinstance(x, tuple):
                    x = x[0]
                return float(x)
            except Exception:
                return 0.0

        # Symbols list (prefer config.symbols; fallback to single symbol)
        symbols = list(getattr(self.config, "symbols", []) or
                       ([getattr(self.config, "symbol", None)] if getattr(self.config, "symbol", None) else []))
        if not symbols:
            logger.warning("No symbols configured; nothing to do")
            return

        # 1) New signals for each configured symbol
        for sym in symbols:
            sig_raw = await _v8_gen(sym)
            sig = _v8_norm_signal(sig_raw, sym)
            if not sig or not sig.symbol or not sig.side:
                continue
            if sig.id in self.processed_signals:
                continue

            # Optional cooldown guard if OrderManager supports it
            try:
                is_cd = getattr(self.order_manager, "is_in_cooldown", None)
                if callable(is_cd):
                    try:
                        in_cd = await is_cd(sig.symbol)
                    except TypeError:
                        # in some builds is_in_cooldown is sync
                        in_cd = is_cd(sig.symbol)
                    if in_cd:
                        continue
            except Exception:
                pass

            # 2) Position sizing with guardrails
            pos_obj = self.active_positions.get(sig.symbol)
            try:
                pos_size = self.risk_manager.calculate_position_size(sig, pos_obj)
            except Exception as e:
                logger.error("Error calculating position size: %s", e)
                pos_size = 0.0

            qty = _v8_coerce_size(pos_size)
            if qty <= 0.0:
                continue

            # Optional risk limit check if available
            try:
                can_open_fn = getattr(self.risk_manager, "can_open_position", None)
                if callable(can_open_fn):
                    if not can_open_fn(sig.symbol, sig.side, qty):
                        logger.warning("Risk limits prevent opening position for %s", sig.symbol)
                        continue
            except Exception:
                pass

            # 3) Place entry order as MARKET
            ex_side = "BUY" if sig.side in ("BUY","LONG") else "SELL"
            try:
                order = await self.order_manager.place_order(
                    symbol=sig.symbol,
                    side=ex_side,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    metadata={"signal_id": sig.id, "strategy": "signal"},
                )
                if order:
                    # keep for status tracking
                    try:
                        oid = getattr(order, "id", None) or getattr(order, "order_id", None)
                        if oid is not None:
                            self.pending_orders[oid] = order
                    except Exception:
                        pass
                    self.processed_signals.add(sig.id)
                    try:
                        o_side = getattr(order, "side", ex_side)
                        logger.info("Order placed: %s %.6f %s", o_side, qty, sig.symbol)
                    except Exception:
                        logger.info("Order placed: %s %.6f %s", ex_side, qty, sig.symbol)
            except Exception as e:
                logger.error("Failed to place order for signal %s: %s", sig.id, e)

        # 4) Manage existing positions, DCA, and order updates
        await self._manage_positions()
        if getattr(self.config, "dca_enabled", False):
            await self._process_dca()
        await self._update_orders()
'''

def main():
    if not LIVE_PATH.exists():
        print(f"File not found: {LIVE_PATH}")
        sys.exit(1)
    src = LIVE_PATH.read_text(encoding="utf-8")

    # 0) Ensure "import time" exists at module level (safe duplicate ok)
    if "import time" not in src:
        # insert after first import block
        src = src.replace("import os", "import os\nimport time")

    # 1) Replace body of async def _process_trading_cycle(...)
    # Pattern with return annotation
    pat1 = re.compile(r"(async def _process_trading_cycle\([^)]*\)\s*->\s*None:\s*)(?:\"\"\"[\s\S]*?\"\"\"\s*)?", re.M)
    m = pat1.search(src)
    if not m:
        # Pattern without annotation
        pat2 = re.compile(r"(async def _process_trading_cycle\([^)]*\)\s*:\s*)(?:\"\"\"[\s\S]*?\"\"\"\s*)?", re.M)
        m = pat2.search(src)
    if not m:
        print("Could not locate _process_trading_cycle(...) in runner/live.py")
        sys.exit(2)

    body_start = m.end()
    # find next method at class indent (4 spaces)
    m2 = re.search(r"\n\s{4}(?:async def|def)\s", src[body_start:])
    if not m2:
        print("Could not find the end of _process_trading_cycle body; aborting for safety.")
        sys.exit(3)
    body_end = body_start + m2.start()

    new_src = src[:body_start] + NEW_BODY + src[body_end:]

    # 2) Backup and write
    backup = LIVE_PATH.with_suffix(".bak_v8_guardrails.py")
    shutil.copy2(LIVE_PATH, backup)
    LIVE_PATH.write_text(new_src, encoding="utf-8")

    print(f"Patched {LIVE_PATH} -> backup: {backup}")

if __name__ == "__main__":
    main()
