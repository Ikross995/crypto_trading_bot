#!/usr/bin/env python3
"""
Structured Logging Infrastructure

Provides centralized, structured logging for the trading system.
Integrates with multiple outputs, log rotation, and performance monitoring.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from core.config import Config


class StructuredLogger:
    """
    Structured logging wrapper that provides consistent formatting,
    contextual information, and multiple output destinations.
    """

    def __init__(self, config: Config):
        self.config = config
        self.log_dir = (
            Path(config.log_dir) if hasattr(config, "log_dir") else Path("logs")
        )
        self.log_dir.mkdir(exist_ok=True)

        # Remove default handler
        logger.remove()

        # Setup handlers
        self._setup_console_handler()
        self._setup_file_handlers()

        # Add context
        self._add_global_context()

    def _setup_console_handler(self) -> None:
        """Setup console logging handler."""
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )

        # Add colorful console handler
        logger.add(
            sys.stdout,
            format=console_format,
            level="INFO",
            colorize=True,
            backtrace=True,
            diagnose=True,
        )

    def _setup_file_handlers(self) -> None:
        """Setup file logging handlers with rotation."""

        # General application log with rotation
        logger.add(
            self.log_dir / "trading_bot.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            level="DEBUG",
            rotation="100 MB",
            retention="30 days",
            compression="gz",
            backtrace=True,
            diagnose=True,
            enqueue=True,  # Thread-safe logging
        )

        # Error-only log
        logger.add(
            self.log_dir / "errors.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            level="ERROR",
            rotation="50 MB",
            retention="90 days",
            compression="gz",
            backtrace=True,
            diagnose=True,
        )

        # Trading-specific logs
        logger.add(
            self.log_dir / "trades.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
            level="INFO",
            filter=lambda record: "TRADE" in record["extra"],
            rotation="10 MB",
            retention="1 year",
        )

        # Performance monitoring log
        logger.add(
            self.log_dir / "performance.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
            level="DEBUG",
            filter=lambda record: "PERF" in record["extra"],
            rotation="20 MB",
            retention="7 days",
        )

        # JSON structured log for external systems
        logger.add(
            self.log_dir / "structured.jsonl",
            format="{time} | {level} | {name} | {message} | {extra}",
            level="INFO",
            rotation="50 MB",
            retention="30 days",
            compression="gz",
            serialize=True,  # Use JSON serialization instead of custom formatter
        )

    def _json_formatter(self, record: dict[str, Any]) -> str:
        """Format log record as JSON."""
        log_entry = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "logger": record["name"],
            "function": record["function"],
            "line": record["line"],
            "message": record["message"],
            "extra": record.get("extra", {}),
        }

        if record.get("exception"):
            log_entry["exception"] = {
                "type": record["exception"].type.__name__,
                "value": str(record["exception"].value),
                "traceback": record["exception"].traceback,
            }

        return json.dumps(log_entry, default=str)

    def _add_global_context(self) -> None:
        """Add global context to all log messages."""
        logger.configure(
            extra={
                "service": "trading-bot",
                "version": "2.0.0",
                "environment": getattr(self.config, "environment", "development"),
                "symbol": getattr(self.config, "symbol", "unknown"),
            }
        )


class TradingLogger:
    """
    Specialized logger for trading operations with structured trade logging.
    """

    @staticmethod
    def log_trade(
        action: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_id: str = None,
        strategy: str = None,
        pnl: float = None,
        **kwargs,
    ) -> None:
        """Log trading action with structured data."""

        trade_data = {
            "action": action,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if order_id:
            trade_data["order_id"] = order_id
        if strategy:
            trade_data["strategy"] = strategy
        if pnl is not None:
            trade_data["pnl"] = pnl

        # Add any additional kwargs
        trade_data.update(kwargs)

        logger.bind(TRADE=True).info(
            f"TRADE {action}: {side} {quantity} {symbol} @ {price}", **trade_data
        )

    @staticmethod
    def log_order_event(
        event: str,
        order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float = None,
        status: str = None,
        **kwargs,
    ) -> None:
        """Log order lifecycle events."""

        order_data = {
            "event": event,
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if price is not None:
            order_data["price"] = price
        if status:
            order_data["status"] = status

        order_data.update(kwargs)

        logger.bind(TRADE=True).info(
            f"ORDER {event}: {order_id} {side} {quantity} {symbol}", **order_data
        )

    @staticmethod
    def log_position_update(
        symbol: str,
        size: float,
        entry_price: float,
        current_price: float,
        unrealized_pnl: float,
        **kwargs,
    ) -> None:
        """Log position updates."""

        position_data = {
            "symbol": symbol,
            "size": size,
            "entry_price": entry_price,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "timestamp": datetime.utcnow().isoformat(),
        }
        position_data.update(kwargs)

        logger.bind(TRADE=True).debug(
            f"POSITION UPDATE: {symbol} size={size} pnl={unrealized_pnl:.2f}",
            **position_data,
        )

    @staticmethod
    def log_signal(
        signal_type: str,
        symbol: str,
        side: str,
        strength: float,
        price: float,
        indicators: dict[str, Any] = None,
        **kwargs,
    ) -> None:
        """Log trading signals."""

        signal_data = {
            "signal_type": signal_type,
            "symbol": symbol,
            "side": side,
            "strength": strength,
            "price": price,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if indicators:
            signal_data["indicators"] = indicators

        signal_data.update(kwargs)

        logger.bind(SIGNAL=True).info(
            f"SIGNAL {signal_type}: {side} {symbol} strength={strength:.2f}",
            **signal_data,
        )


class PerformanceLogger:
    """
    Logger for performance monitoring and system metrics.
    """

    @staticmethod
    def log_execution_time(
        operation: str, duration_ms: float, success: bool = True, **kwargs
    ) -> None:
        """Log operation execution time."""

        perf_data = {
            "operation": operation,
            "duration_ms": duration_ms,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
        }
        perf_data.update(kwargs)

        level = "DEBUG" if success else "WARNING"
        logger.bind(PERF=True).log(
            level, f"PERF {operation}: {duration_ms:.2f}ms", **perf_data
        )

    @staticmethod
    def log_system_metrics(
        memory_usage_mb: float,
        cpu_percent: float,
        active_positions: int,
        pending_orders: int,
        **kwargs,
    ) -> None:
        """Log system performance metrics."""

        metrics_data = {
            "memory_usage_mb": memory_usage_mb,
            "cpu_percent": cpu_percent,
            "active_positions": active_positions,
            "pending_orders": pending_orders,
            "timestamp": datetime.utcnow().isoformat(),
        }
        metrics_data.update(kwargs)

        logger.bind(PERF=True).debug(
            f"SYSTEM METRICS: mem={memory_usage_mb:.1f}MB cpu={cpu_percent:.1f}% "
            f"positions={active_positions} orders={pending_orders}",
            **metrics_data,
        )

    @staticmethod
    def log_api_call(
        endpoint: str,
        method: str,
        duration_ms: float,
        status_code: int,
        success: bool,
        **kwargs,
    ) -> None:
        """Log API call performance."""

        api_data = {
            "endpoint": endpoint,
            "method": method,
            "duration_ms": duration_ms,
            "status_code": status_code,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
        }
        api_data.update(kwargs)

        level = "DEBUG" if success else "WARNING"
        logger.bind(PERF=True).log(
            level,
            f"API {method} {endpoint}: {status_code} ({duration_ms:.2f}ms)",
            **api_data,
        )


def setup_structured_logging(config: Config) -> StructuredLogger:
    """
    Setup structured logging for the application.

    Args:
        config: Application configuration

    Returns:
        Configured StructuredLogger instance
    """
    structured_logger = StructuredLogger(config)

    # Log initialization
    logger.info(
        "Structured logging initialized",
        log_dir=str(structured_logger.log_dir),
        environment=getattr(config, "environment", "development"),
    )

    return structured_logger


def get_logger(name: str = None) -> Any:
    """
    Get a logger instance.

    Args:
        name: Logger name (optional)

    Returns:
        Logger instance
    """
    if name:
        return logger.bind(component=name)
    return logger


# Context managers for logging contexts
class LoggingContext:
    """Context manager for adding temporary logging context."""

    def __init__(self, **context):
        self.context = context
        self.token = None

    def __enter__(self):
        self.token = logger.contextualize(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            self.token.__exit__(exc_type, exc_val, exc_tb)


def with_logging_context(**context):
    """Decorator to add logging context to a function."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            with LoggingContext(**context):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# Export main interfaces
trading_logger = TradingLogger()
performance_logger = PerformanceLogger()

__all__ = [
    "setup_structured_logging",
    "get_logger",
    "StructuredLogger",
    "TradingLogger",
    "PerformanceLogger",
    "LoggingContext",
    "with_logging_context",
    "trading_logger",
    "performance_logger",
]
