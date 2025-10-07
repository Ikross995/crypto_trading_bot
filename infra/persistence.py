#!/usr/bin/env python3
"""
Data Persistence Infrastructure

Provides persistent storage for trading bot state, configuration,
historical data, and performance metrics.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from core.config import Config
from core.types import Order, Position, Signal, Trade


class StateManager:
    """
    Manages bot state persistence to survive restarts and failures.
    Stores active positions, pending orders, and runtime state.
    """

    def __init__(self, config: Config):
        self.config = config
        self.data_dir = (
            Path(config.data_dir) if hasattr(config, "data_dir") else Path("data")
        )
        self.data_dir.mkdir(exist_ok=True)

        self.state_file = self.data_dir / "bot_state.json"
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)

        logger.info(f"StateManager initialized: {self.state_file}")

    async def save_state(self, state: dict[str, Any], state_type: str = "main") -> bool:
        """
        Save current bot state to persistent storage.

        Args:
            state: State dictionary to save
            state_type: Type of state (main, paper, backtest, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            state_file = self.data_dir / f"bot_state_{state_type}.json"

            state_with_meta = {
                "timestamp": datetime.utcnow().isoformat(),
                "state_type": state_type,
                "version": "2.0.0",
                "data": state,
            }

            # Create backup first
            await self._create_backup(state_file)

            # Write new state
            with open(state_file, "w") as f:
                json.dump(state_with_meta, f, indent=2, default=str)

            logger.debug(f"State saved: {state_file}")
            return True

        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return False

    async def load_state(self, state_type: str = "main") -> dict[str, Any] | None:
        """
        Load bot state from persistent storage.

        Args:
            state_type: Type of state to load

        Returns:
            State dictionary if found, None otherwise
        """
        try:
            state_file = self.data_dir / f"bot_state_{state_type}.json"

            if not state_file.exists():
                logger.debug(f"No saved state found: {state_file}")
                return None

            with open(state_file) as f:
                state_with_meta = json.load(f)

            # Validate state
            if not self._validate_state(state_with_meta):
                logger.warning(f"Invalid state format in {state_file}")
                return None

            logger.info(
                f"State loaded: {state_file} "
                f"(saved: {state_with_meta.get('timestamp', 'unknown')})"
            )

            return state_with_meta["data"]

        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None

    async def _create_backup(self, state_file: Path) -> None:
        """Create backup of existing state file."""
        try:
            if not state_file.exists():
                return

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"{state_file.stem}_{timestamp}.json"

            # Copy current state to backup
            with open(state_file) as src, open(backup_file, "w") as dst:
                dst.write(src.read())

            # Clean old backups (keep last 10)
            self._cleanup_old_backups()

        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")

    def _cleanup_old_backups(self) -> None:
        """Clean up old backup files, keeping only the most recent."""
        try:
            backup_files = sorted(
                self.backup_dir.glob("*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )

            # Keep only last 10 backups
            for old_backup in backup_files[10:]:
                old_backup.unlink()
                logger.debug(f"Removed old backup: {old_backup}")

        except Exception as e:
            logger.error(f"Failed to cleanup backups: {e}")

    def _validate_state(self, state: dict[str, Any]) -> bool:
        """Validate state structure."""
        required_fields = ["timestamp", "state_type", "version", "data"]
        return all(field in state for field in required_fields)


class DataPersistence:
    """
    Persistent storage for trading data using SQLite.
    Stores trades, orders, positions, signals, and performance metrics.
    """

    def __init__(self, config: Config):
        self.config = config
        self.data_dir = (
            Path(config.data_dir) if hasattr(config, "data_dir") else Path("data")
        )
        self.data_dir.mkdir(exist_ok=True)

        self.db_path = self.data_dir / "trading_data.db"
        self._init_database()

        logger.info(f"DataPersistence initialized: {self.db_path}")

    def _init_database(self) -> None:
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                -- Trades table
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    quantity REAL NOT NULL,
                    pnl REAL DEFAULT 0,
                    entry_time TIMESTAMP NOT NULL,
                    exit_time TIMESTAMP,
                    strategy TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Orders table
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL,
                    status TEXT NOT NULL,
                    executed_qty REAL DEFAULT 0,
                    avg_price REAL,
                    timestamp TIMESTAMP NOT NULL,
                    fill_timestamp TIMESTAMP,
                    commission REAL DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Positions table
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL,
                    unrealized_pnl REAL,
                    entry_time TIMESTAMP NOT NULL,
                    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}'
                );

                -- Signals table
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    signal_type TEXT DEFAULT 'unknown',
                    strength REAL NOT NULL,
                    price REAL NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    indicators TEXT DEFAULT '{}',
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Performance metrics table
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_type TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    symbol TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}'
                );

                -- Create indexes for better query performance
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, entry_time);
                CREATE INDEX IF NOT EXISTS idx_orders_symbol_time ON orders(symbol, timestamp);
                CREATE INDEX IF NOT EXISTS idx_positions_symbol_time ON positions(symbol, snapshot_time);
                CREATE INDEX IF NOT EXISTS idx_metrics_type_time ON performance_metrics(metric_type, timestamp);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol_time ON signals(symbol, timestamp);
            """
            )

    async def save_trade(self, trade: Trade) -> bool:
        """Save completed trade to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trades
                    (id, symbol, side, entry_price, exit_price, quantity, pnl,
                     entry_time, exit_time, strategy, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        trade.id,
                        trade.symbol,
                        (
                            trade.side.value
                            if hasattr(trade.side, "value")
                            else str(trade.side)
                        ),
                        trade.entry_price,
                        trade.exit_price,
                        trade.quantity,
                        trade.pnl,
                        trade.entry_time,
                        trade.exit_time,
                        trade.strategy,
                        json.dumps(getattr(trade, "metadata", {}), default=str),
                    ),
                )

            logger.debug(f"Trade saved: {trade.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save trade {trade.id}: {e}")
            return False

    async def save_order(self, order: Order) -> bool:
        """Save order to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO orders
                    (id, symbol, side, order_type, quantity, price, status,
                     executed_qty, avg_price, timestamp, fill_timestamp, commission, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        order.id,
                        order.symbol,
                        (
                            order.side.value
                            if hasattr(order.side, "value")
                            else str(order.side)
                        ),
                        (
                            order.order_type.value
                            if hasattr(order.order_type, "value")
                            else str(order.order_type)
                        ),
                        order.quantity,
                        order.price,
                        order.status,
                        getattr(order, "executed_qty", 0),
                        getattr(order, "avg_price", None),
                        order.timestamp,
                        getattr(order, "fill_timestamp", None),
                        getattr(order, "commission", 0),
                        json.dumps(getattr(order, "metadata", {}), default=str),
                    ),
                )

            logger.debug(f"Order saved: {order.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save order {order.id}: {e}")
            return False

    async def save_position_snapshot(self, position: Position) -> bool:
        """Save position snapshot to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO positions
                    (symbol, side, size, entry_price, current_price, unrealized_pnl,
                     entry_time, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        position.symbol,
                        (
                            position.side.value
                            if hasattr(position.side, "value")
                            else str(position.side)
                        ),
                        position.size,
                        position.entry_price,
                        getattr(position, "current_price", None),
                        getattr(position, "unrealized_pnl", None),
                        position.entry_time,
                        json.dumps(getattr(position, "metadata", {}), default=str),
                    ),
                )

            return True

        except Exception as e:
            logger.error(f"Failed to save position snapshot: {e}")
            return False

    async def save_signal(self, signal: Signal) -> bool:
        """Save trading signal to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO signals
                    (id, symbol, side, signal_type, strength, price, timestamp, indicators, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        signal.id,
                        signal.symbol,
                        (
                            signal.side.value
                            if hasattr(signal.side, "value")
                            else str(signal.side)
                        ),
                        getattr(signal, "signal_type", "unknown"),
                        signal.strength,
                        signal.price,
                        signal.timestamp,
                        json.dumps(getattr(signal, "indicators", {}), default=str),
                        json.dumps(getattr(signal, "metadata", {}), default=str),
                    ),
                )

            logger.debug(f"Signal saved: {signal.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save signal {signal.id}: {e}")
            return False

    async def save_metric(
        self,
        metric_type: str,
        metric_name: str,
        metric_value: float,
        symbol: str = None,
        metadata: dict[str, Any] = None,
    ) -> bool:
        """Save performance metric to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO performance_metrics
                    (metric_type, metric_name, metric_value, symbol, metadata)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        metric_type,
                        metric_name,
                        metric_value,
                        symbol,
                        json.dumps(metadata or {}, default=str),
                    ),
                )

            return True

        except Exception as e:
            logger.error(f"Failed to save metric {metric_name}: {e}")
            return False

    async def get_trades(
        self,
        symbol: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = None,
    ) -> list[dict[str, Any]]:
        """Retrieve trades from database."""
        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params = []

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            if start_date:
                query += " AND entry_time >= ?"
                params.append(start_date)

            if end_date:
                query += " AND entry_time <= ?"
                params.append(end_date)

            query += " ORDER BY entry_time DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, params)
                trades = [dict(row) for row in cursor.fetchall()]

            return trades

        except Exception as e:
            logger.error(f"Failed to retrieve trades: {e}")
            return []

    async def get_performance_summary(
        self, start_date: datetime = None, end_date: datetime = None
    ) -> dict[str, Any]:
        """Get performance summary from stored trades."""
        try:
            trades = await self.get_trades(start_date=start_date, end_date=end_date)

            if not trades:
                return {}

            total_trades = len(trades)
            winning_trades = len([t for t in trades if t["pnl"] > 0])
            losing_trades = total_trades - winning_trades

            total_pnl = sum(t["pnl"] for t in trades)
            avg_win = sum(t["pnl"] for t in trades if t["pnl"] > 0) / max(
                1, winning_trades
            )
            avg_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0) / max(
                1, losing_trades
            )

            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            profit_factor = abs(avg_win * winning_trades) / max(
                1, abs(avg_loss * losing_trades)
            )

            return {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "profit_factor": profit_factor,
                "best_trade": (
                    max(trades, key=lambda x: x["pnl"])["pnl"] if trades else 0
                ),
                "worst_trade": (
                    min(trades, key=lambda x: x["pnl"])["pnl"] if trades else 0
                ),
            }

        except Exception as e:
            logger.error(f"Failed to generate performance summary: {e}")
            return {}

    async def cleanup_old_data(self, days_to_keep: int = 30) -> bool:
        """Clean up old data from database."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

            with sqlite3.connect(self.db_path) as conn:
                # Clean old position snapshots (keep trades and orders)
                cursor = conn.execute(
                    "DELETE FROM positions WHERE snapshot_time < ?", (cutoff_date,)
                )
                positions_deleted = cursor.rowcount

                # Clean old performance metrics
                cursor = conn.execute(
                    "DELETE FROM performance_metrics WHERE timestamp < ?",
                    (cutoff_date,),
                )
                metrics_deleted = cursor.rowcount

                # Clean old signals
                cursor = conn.execute(
                    "DELETE FROM signals WHERE created_at < ?", (cutoff_date,)
                )
                signals_deleted = cursor.rowcount

            logger.info(
                f"Data cleanup completed: {positions_deleted} positions, "
                f"{metrics_deleted} metrics, {signals_deleted} signals removed"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
            return False

    async def export_data(
        self, table_name: str, output_file: Path, format_type: str = "csv"
    ) -> bool:
        """Export database table to file."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)

                if format_type.lower() == "csv":
                    df.to_csv(output_file, index=False)
                elif format_type.lower() == "parquet":
                    df.to_parquet(output_file, index=False)
                elif format_type.lower() == "json":
                    df.to_json(output_file, orient="records", date_format="iso")
                else:
                    raise ValueError(f"Unsupported format: {format_type}")

            logger.info(f"Exported {len(df)} rows from {table_name} to {output_file}")
            return True

        except Exception as e:
            logger.error(f"Failed to export data: {e}")
            return False


class CacheManager:
    """
    In-memory cache with TTL support for frequently accessed data.
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, dict[str, Any]] = {}
        self._access_times: dict[str, datetime] = {}

    async def get(self, key: str) -> Any | None:
        """Get cached value."""
        if key not in self._cache:
            return None

        # Check if expired
        entry = self._cache[key]
        if datetime.utcnow() > entry["expiry"]:
            await self.delete(key)
            return None

        # Update access time
        self._access_times[key] = datetime.utcnow()
        return entry["value"]

    async def set(
        self, key: str, value: Any, ttl_seconds: int = None
    ) -> bool:
        """Set cached value with optional TTL."""
        try:
            # Clean up if needed
            await self._cleanup()

            ttl = ttl_seconds or self.ttl_seconds
            expiry = datetime.utcnow() + timedelta(seconds=ttl)

            self._cache[key] = {"value": value, "expiry": expiry}
            self._access_times[key] = datetime.utcnow()

            return True

        except Exception as e:
            logger.error(f"Failed to cache value for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete cached value."""
        try:
            if key in self._cache:
                del self._cache[key]
            if key in self._access_times:
                del self._access_times[key]
            return True

        except Exception as e:
            logger.error(f"Failed to delete cache key {key}: {e}")
            return False

    async def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()
        self._access_times.clear()

    async def _cleanup(self) -> None:
        """Clean up expired and excess items."""
        current_time = datetime.utcnow()

        # Remove expired items
        expired_keys = [
            key for key, data in self._cache.items() if current_time > data["expiry"]
        ]

        for key in expired_keys:
            await self.delete(key)

        # If still too many items, remove least recently used
        if len(self._cache) >= self.max_size:
            # Sort by access time
            sorted_keys = sorted(
                self._access_times.keys(), key=lambda k: self._access_times[k]
            )

            # Remove oldest 20% of items
            remove_count = max(1, len(sorted_keys) // 5)
            for key in sorted_keys[:remove_count]:
                await self.delete(key)


__all__ = ["StateManager", "DataPersistence", "CacheManager"]