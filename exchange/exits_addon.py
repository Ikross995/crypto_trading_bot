# exchange/exits_addon.py
# Безопасная заглушка: импортируется runner.execution, но в DRY_RUN/Testnet ничем не мешает.
from typing import Any, Dict

def ensure_exits_on_exchange(symbol: str, side: str, qty: float, entry: float, stop: float) -> Dict[str, Any]:
    """
    Контракт функции сохранён. В Live можно заменить реализацией,
    если у вас есть готовая логика выставления SL/TP на бирже.
    Сейчас — no-op: не падаем на импорте и ничего не ломаем.
    """
    return {"status": "SKIP", "reason": "exits_addon shim active", "placed": False}
