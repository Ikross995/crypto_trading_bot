# exchange/positions.py
"""
Position management for AI Trading Bot.

Handles position tracking, P&L calculations, and position-related operations.
"""
import time
import logging
from typing import Dict, List, Optional
from datetime import datetime

from core.config import get_config
from core.types import Position
from .client import BinanceClient

logger = logging.getLogger(__name__)


class PositionManager:
    """
    Position manager for tracking and managing futures positions.

    Features:
    - Real-time position tracking
    - P&L calculation
    - Position sizing validation
    - Risk metrics

    Added in this revision:
    - Missing compat async adapters moved INSIDE the class
    - get_position() implementation and cache/TTL
    - Uses client.get_position_info() alias and robust key mapping (unRealizedProfit vs unPnl)
    - get_account_balance() returns float using client method
    """

    def __init__(self, client: BinanceClient):
        self.client = client
        self.config = get_config()

        # Position cache to reduce API calls
        self._positions_cache: Dict[str, Position] = {}
        self._last_update = 0.0
        self._cache_ttl = 5.0  # Cache for 5 seconds

    # --- async adapters expected by live engine ---
    async def initialize(self) -> None:
        """
        Async initialization to match live engine expectations.
        Configures symbols via setup_symbol.
        """
        cfg = self.config
        raw: List[str] = []
        if getattr(cfg, "symbol", None):
            raw.append(cfg.symbol)
        if getattr(cfg, "symbols", None):
            raw.extend(cfg.symbols if isinstance(cfg.symbols, (list, tuple)) else [cfg.symbols])

        ordered, seen = [], set()
        for s in raw:
            if s and s not in seen:
                ordered.append(s); seen.add(s)

        for sym in ordered:
            try:
                self.setup_symbol(sym)
            except Exception:
                # don't fail overall init
                pass

    async def get_positions(self):
        """
        Return current positions for symbols from config (engine expects this).
        """
        cfg = self.config
        raw: List[str] = []
        if getattr(cfg, "symbol", None):
            raw.append(cfg.symbol)
        if getattr(cfg, "symbols", None):
            raw.extend(cfg.symbols if isinstance(cfg.symbols, (list, tuple)) else [cfg.symbols])

        ordered, seen = [], set()
        for s in raw:
            if s and s not in seen:
                ordered.append(s); seen.add(s)

        result = []
        for sym in ordered:
            pos = self.get_position(sym, force_refresh=True)
            if pos is not None:
                self._positions_cache[sym] = pos
                result.append(pos)
        return result

    async def update_position(self, position):
        """
        Refresh specified position by its symbol and return updated instance.
        """
        sym = getattr(position, "symbol", None)
        if sym is None and isinstance(position, dict):
            sym = position.get("symbol")
        if not sym:
            return position
        return self.get_position(sym, force_refresh=True)

    async def handle_filled_order(self, order):
        """
        Hook after order fill: refresh cached position by symbol.
        """
        sym = getattr(order, "symbol", None)
        if sym is None and isinstance(order, dict):
            sym = order.get("symbol")
        if sym:
            self.get_position(sym, force_refresh=True)

    async def sync_positions(self):
        """
        Periodic sync: reload all positions and update cache.
        """
        positions = await self.get_positions()
        for p in positions:
            sym = getattr(p, "symbol", None)
            if sym:
                self._positions_cache[sym] = p

    # --- core API ---
    def get_position(self, symbol: str, force_refresh: bool = False) -> Optional[Position]:
        """Return single-symbol Position object or None (flat)."""
        sym = symbol.upper()
        now = time.time()
        if not force_refresh and sym in self._positions_cache and (now - self._last_update) < self._cache_ttl:
            return self._positions_cache.get(sym)

        try:
            data = self.client.get_position_info()  # list of dicts
            for pos in data:
                if str(pos.get("symbol", "")).upper() != sym:
                    continue
                amt = float(pos.get("positionAmt", "0") or 0.0)
                if abs(amt) <= 1e-12:
                    # flat
                    p = Position(symbol=sym, side=0, size=0.0, entry_price=0.0,
                                 unrealized_pnl=0.0, timestamp=datetime.now())
                    self._positions_cache[sym] = p
                    self._last_update = now
                    return p
                entry = float(pos.get("entryPrice", "0") or 0.0)
                # UM futures key is 'unRealizedProfit'
                upnl = pos.get("unRealizedProfit", pos.get("unPnl", "0"))
                upnl = float(upnl or 0.0)
                p = Position(
                    symbol=sym,
                    side=1 if amt > 0 else -1,
                    size=abs(amt),
                    entry_price=entry,
                    unrealized_pnl=upnl,
                    timestamp=datetime.now()
                )
                self._positions_cache[sym] = p
                self._last_update = now
                return p
        except Exception as e:
            logger.error(f"Failed to get position for {sym}: {e}")
            return None
        return None

    def get_all_positions(self, force_refresh: bool = False) -> List[Position]:
        """
        Get all open positions.
        """
        try:
            positions = []
            position_data = self.client.get_position_info()
            for pos in position_data:
                amt = float(pos.get("positionAmt", "0") or 0.0)
                if abs(amt) <= 1e-12:
                    continue
                symbol = str(pos.get("symbol", "")).upper()
                entry = float(pos.get("entryPrice", "0") or 0.0)
                upnl = pos.get("unRealizedProfit", pos.get("unPnl", "0"))
                upnl = float(upnl or 0.0)
                position = Position(
                    symbol=symbol,
                    side=1 if amt > 0 else -1,
                    size=abs(amt),
                    entry_price=entry,
                    unrealized_pnl=upnl,
                    timestamp=datetime.now()
                )
                positions.append(position)
                self._positions_cache[symbol] = position
            self._last_update = time.time()
            return positions
        except Exception as e:
            logger.error(f"Failed to get all positions: {e}")
            return []

    def get_account_balance(self) -> float:
        """
        Get account balance in USDT as float.
        """
        try:
            return float(self.client.get_account_balance() or 0.0)
        except Exception as e:
            logger.error(f"Failed to get account balance: {e}")
            return 0.0

    def calculate_position_size(self, symbol: str, entry_price: float,
                                stop_loss_price: float) -> float:
        """
        Calculate position size based on risk management rules.
        """
        try:
            balance = self.get_account_balance()
            if balance <= 0:
                return 0.0

            risk_amount = balance * (self.config.risk_per_trade_pct / 100.0)

            if stop_loss_price <= 0:
                sl_distance = entry_price * (self.config.sl_fixed_pct / 100.0)
            else:
                sl_distance = abs(entry_price - stop_loss_price)
            if sl_distance <= 0:
                return 0.0

            position_size = risk_amount / sl_distance
            position_size *= self.config.leverage

            min_notional = float(self.config.min_notional_usdt or 5.0)
            if position_size * entry_price < min_notional:
                position_size = min_notional / max(1e-9, entry_price)

            return position_size
        except Exception as e:
            logger.error(f"Failed to calculate position size for {symbol}: {e}")
            return 0.0

    def get_position_risk_metrics(self, symbol: str) -> Dict[str, float]:
        """
        Calculate risk metrics for a position.
        """
        position = self.get_position(symbol) or Position(symbol=symbol.upper(), side=0, size=0.0, entry_price=0.0,
                                                         unrealized_pnl=0.0, timestamp=datetime.now())
        balance = self.get_account_balance()

        if position.is_flat or balance <= 0:
            return {
                "position_size_usd": 0.0,
                "account_risk_pct": 0.0,
                "leverage_used": 0.0,
                "unrealized_pnl_pct": 0.0
            }

        try:
            t = self.client.get_ticker_price(symbol)
            current_price = float(t.get("price", "0") or 0.0)
            position_value = position.size * current_price
            account_risk_pct = (position_value / balance) * 100.0 / max(1e-9, float(self.config.leverage or 1))
            leverage_used = position_value / max(1e-9, balance)
            unrealized_pnl_pct = (position.unrealized_pnl / max(1e-9, balance)) * 100.0
            return {
                "position_size_usd": position_value,
                "account_risk_pct": account_risk_pct,
                "leverage_used": leverage_used,
                "unrealized_pnl_pct": unrealized_pnl_pct
            }
        except Exception as e:
            logger.error(f"Failed to calculate risk metrics for {symbol}: {e}")
            return {
                "position_size_usd": 0.0,
                "account_risk_pct": 0.0,
                "leverage_used": 0.0,
                "unrealized_pnl_pct": 0.0
            }

    def setup_symbol(self, symbol: str) -> bool:
        """
        Setup symbol for trading (leverage, margin type, position mode).
        """
        try:
            # leverage
            self.client.change_leverage(symbol, int(self.config.leverage))
            logger.info(f"Set leverage for {symbol}: {self.config.leverage}x")

            # margin type (default isolated)
            margin_type = getattr(self.config, "margin_type", "ISOLATED") or "ISOLATED"
            try:
                self.client.change_margin_type(symbol, margin_type)
                logger.info(f"Set margin type for {symbol}: {margin_type}")
            except Exception:
                pass  # already set

            # position mode (ONEWAY/HEDGE)
            try:
                dual_side = (str(getattr(self.config, "position_mode", "ONEWAY")).upper() == "HEDGE")
                self.client.change_position_mode(dual_side)
                logger.info(f"Set position mode: {'HEDGE' if dual_side else 'ONE-WAY'}")
            except Exception:
                pass

            return True
        except Exception as e:
            logger.error(f"Failed to setup symbol {symbol}: {e}")
            return False

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """Clear position cache for symbol or all."""
        if symbol:
            self._positions_cache.pop(symbol.upper(), None)
        else:
            self._positions_cache.clear()
        logger.debug(f"Cleared position cache for {symbol or 'all symbols'}")
