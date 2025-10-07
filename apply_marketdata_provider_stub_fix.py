# apply_marketdata_provider_stub_fix.py
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
MD_PATH = BASE / "exchange" / "market_data.py"

STUB = r'''
# --- AUTO-ADDED SAFE STUB: MarketDataProvider ---------------------------------
# Этот блок добавляется только если класс MarketDataProvider ещё не определён
# в модуле. Ничего не ломает и не конфликтует с вашей логикой.
try:
    MarketDataProvider  # type: ignore[name-defined]
except NameError:  # nosec - проверяем наличие имени в модуле
    import asyncio
    import logging
    from typing import Dict, List, Optional, Any

    class MarketDataProvider:
        """
        Minimal/compatible MarketDataProvider для live/paper:
          - start()/stop() — no-op
          - last_price(symbol) -> float|None
          - fetch_klines(symbol, limit=200) -> List[dict]
          - update_from_ws(symbol, price) — обновление локального last_price
        Если у переданного client есть методы get_price_ticker/get_klines — используем их.
        Иначе возвращаем безопасные значения (None или []).
        """
        def __init__(self, client: Any = None, *, symbols=None, timeframe: str = "1m", logger=None) -> None:
            self.client = client
            self.symbols = list(symbols or [])
            self.timeframe = timeframe
            self.log = logger or logging.getLogger(__name__)
            self._last_price: Dict[str, float] = {}

        async def start(self) -> None:
            return

        async def stop(self) -> None:
            return

        async def last_price(self, symbol: str) -> Optional[float]:
            # 1) локальный кэш
            p = self._last_price.get(symbol)
            if p:
                return p
            # 2) REST: client.get_price_ticker
            try:
                if self.client and hasattr(self.client, "get_price_ticker"):
                    data = await self._maybe_await(self.client.get_price_ticker(symbol))
                    if isinstance(data, (int, float)):
                        p = float(data)
                    elif isinstance(data, dict) and "price" in data:
                        p = float(data["price"])
                    else:
                        p = None
                    if p:
                        self._last_price[symbol] = p
                    return p
            except Exception as e:
                self.log.debug("last_price(%s) via REST failed: %s", symbol, e)
            return None

        async def fetch_klines(self, symbol: str, limit: int = 200) -> List[dict]:
            # Если client.get_klines есть — нормализуем ответ в список dict
            try:
                if self.client and hasattr(self.client, "get_klines"):
                    kl = await self._maybe_await(self.client.get_klines(symbol=symbol, interval=self.timeframe, limit=limit))
                    out: List[dict] = []
                    for row in kl or []:
                        if isinstance(row, dict):
                            out.append(row)
                        elif isinstance(row, (list, tuple)) and len(row) >= 6:
                            out.append({
                                "open_time": row[0],
                                "open": float(row[1]),
                                "high": float(row[2]),
                                "low": float(row[3]),
                                "close": float(row[4]),
                                "volume": float(row[5]),
                                "close_time": row[6] if len(row) > 6 else None,
                            })
                    return out
            except Exception as e:
                self.log.debug("fetch_klines(%s) failed: %s", symbol, e)
            return []

        def update_from_ws(self, symbol: str, price: float) -> None:
            try:
                self._last_price[symbol] = float(price)
            except Exception:
                pass

        async def _maybe_await(self, x):
            if asyncio.iscoroutine(x):
                return await x
            return x

    __all__ = [*(globals().get("__all__", []) or []), "MarketDataProvider"]
# --- END OF STUB ---------------------------------------------------------------
'''

def main():
    if MD_PATH.exists():
        backup = MD_PATH.with_suffix(".bak_marketdata_stub")
        shutil.copy2(MD_PATH, backup)
        txt = MD_PATH.read_text(encoding="utf-8", errors="ignore")
        if "class MarketDataProvider" in txt:
            # Класс уже есть — ничего не делаем
            print("✔ exchange/market_data.py уже содержит MarketDataProvider (патч не нужен)")
            return
        # Аппендим stub в конец (ничего не затираем)
        MD_PATH.write_text(txt.rstrip() + "\n\n" + STUB, encoding="utf-8")
        print(f"✔ Добавлен STUB в exchange/market_data.py (backup: {backup.name})")
    else:
        # Файла нет — создаём с чистым STUB
        MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        MD_PATH.write_text(STUB.lstrip(), encoding="utf-8")
        print("✔ Создан exchange/market_data.py со STUB MarketDataProvider")

if __name__ == "__main__":
    main()
