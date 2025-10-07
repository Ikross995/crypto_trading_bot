#!/usr/bin/env python3
"""
Performance Metrics and Monitoring

Comprehensive performance tracking, system monitoring, and metrics collection
for the trading bot infrastructure.
"""

import asyncio
import statistics
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from loguru import logger

from core.config import Config
from core.types import Order


@dataclass
class PerformanceMetric:
    """Individual performance metric data."""

    name: str
    value: float
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemMetrics:
    """System resource utilization metrics."""

    timestamp: datetime
    cpu_percent: float
    memory_usage_mb: float
    memory_percent: float
    disk_usage_gb: float
    disk_percent: float
    network_sent_mb: float = 0.0
    network_recv_mb: float = 0.0


class MetricsCollector:
    """
    Centralized metrics collection and performance monitoring.

    Features:
    - System resource monitoring
    - Trading performance metrics
    - API call latency tracking
    - Custom metric collection
    - Real-time alerting
    """

    def __init__(self, config: Config):
        self.config = config
        self.running = False

        # Metrics storage
        self.performance_metrics: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self.system_metrics: deque = deque(maxlen=100)
        self.api_latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

        # Trading metrics
        self.trade_metrics = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "consecutive_errors": 0,
            "last_error_time": None,
        }

        # System monitoring
        self.start_time = datetime.utcnow()
        self.last_system_check = datetime.utcnow()

        # Alerting thresholds
        self.alert_thresholds = {
            "cpu_percent": 80.0,
            "memory_percent": 85.0,
            "disk_percent": 90.0,
            "api_latency_ms": 5000.0,
            "consecutive_errors": 5,
            "max_drawdown": 0.10,  # 10%
        }

        # Alert callbacks
        self.alert_callbacks: list[Callable] = []

        logger.info("MetricsCollector initialized")

    async def start(self) -> None:
        """Start metrics collection."""
        if self.running:
            return

        self.running = True
        self.start_time = datetime.utcnow()

        # Start background monitoring
        asyncio.create_task(self._monitoring_loop())

        logger.info("Metrics collection started")

    async def stop(self) -> None:
        """Stop metrics collection."""
        self.running = False
        logger.info("Metrics collection stopped")

    async def _monitoring_loop(self) -> None:
        """Background monitoring loop."""
        while self.running:
            try:
                # Collect system metrics every 30 seconds
                await self._collect_system_metrics()

                # Check alert conditions
                await self._check_alerts()

                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    async def _collect_system_metrics(self) -> None:
        """Collect current system metrics."""
        if not PSUTIL_AVAILABLE:
            return
            
        try:
            # CPU and Memory
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()

            # Disk usage
            disk = psutil.disk_usage("/")

            # Network (optional, may not be available in all environments)
            network_sent_mb = 0.0
            network_recv_mb = 0.0
            try:
                net_io = psutil.net_io_counters()
                if hasattr(net_io, "bytes_sent"):
                    network_sent_mb = net_io.bytes_sent / (1024 * 1024)
                    network_recv_mb = net_io.bytes_recv / (1024 * 1024)
            except Exception:
                pass  # Network stats not critical

            metrics = SystemMetrics(
                timestamp=datetime.utcnow(),
                cpu_percent=cpu_percent,
                memory_usage_mb=memory.used / (1024 * 1024),
                memory_percent=memory.percent,
                disk_usage_gb=disk.used / (1024 * 1024 * 1024),
                disk_percent=(disk.used / disk.total) * 100,
                network_sent_mb=network_sent_mb,
                network_recv_mb=network_recv_mb,
            )

            self.system_metrics.append(metrics)

            # Log detailed metrics periodically (every 5 minutes)
            if len(self.system_metrics) % 10 == 0:
                logger.debug(
                    f"System metrics: CPU {cpu_percent:.1f}%, "
                    f"Memory {memory.percent:.1f}%, "
                    f"Disk {metrics.disk_percent:.1f}%"
                )

        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")

    def record_metric(
        self, name: str, value: float, metadata: dict[str, Any] = None
    ) -> None:
        """Record a custom performance metric."""
        metric = PerformanceMetric(
            name=name, value=value, timestamp=datetime.utcnow(), metadata=metadata or {}
        )

        self.performance_metrics[name].append(metric)

    def record_trade(self, order: Order) -> None:
        """Record trading metrics from an executed order."""
        self.trade_metrics["total_trades"] += 1

        # If this is a closing order, we can calculate P&L
        if hasattr(order, "pnl") and order.pnl is not None:
            pnl = order.pnl
            self.trade_metrics["total_pnl"] += pnl

            if pnl > 0:
                self.trade_metrics["winning_trades"] += 1
            else:
                self.trade_metrics["losing_trades"] += 1

            # Update drawdown tracking
            self._update_drawdown()

        # Reset consecutive errors on successful trade
        self.trade_metrics["consecutive_errors"] = 0

        # Record trade execution time if available
        if hasattr(order, "execution_time_ms"):
            self.record_metric("trade_execution_ms", order.execution_time_ms)

    def record_api_call(
        self, endpoint: str, duration_ms: float, success: bool = True
    ) -> None:
        """Record API call latency and success."""
        self.api_latencies[endpoint].append(duration_ms)

        # Record as metric
        self.record_metric(
            f"api_latency_{endpoint}",
            duration_ms,
            {"success": success, "endpoint": endpoint},
        )

        if not success:
            self.increment_error_count()

    def record_loop_time(self, duration_ms: float) -> None:
        """Record main trading loop execution time."""
        self.record_metric("loop_duration_ms", duration_ms)

    def increment_error_count(self) -> None:
        """Increment consecutive error count."""
        self.trade_metrics["consecutive_errors"] += 1
        self.trade_metrics["last_error_time"] = datetime.utcnow()

        # Record error metric
        self.record_metric(
            "consecutive_errors", self.trade_metrics["consecutive_errors"]
        )

    def increment_health_check_failures(self) -> None:
        """Increment health check failure count."""
        self.record_metric("health_check_failures", 1)

    def update_positions_count(self, count: int) -> None:
        """Update active positions count."""
        self.record_metric("active_positions", count)

    def update_total_position_value(self, value: float) -> None:
        """Update total position value."""
        self.record_metric("total_position_value", value)

    def update_total_pnl(self, pnl: float) -> None:
        """Update total P&L."""
        self.trade_metrics["total_pnl"] = pnl
        self.record_metric("total_pnl", pnl)

    def update_balance(self, balance: float) -> None:
        """Update account balance."""
        self.record_metric("account_balance", balance)

    def update_max_drawdown(self, drawdown: float) -> None:
        """Update maximum drawdown."""
        if drawdown > self.trade_metrics["max_drawdown"]:
            self.trade_metrics["max_drawdown"] = drawdown
            self.record_metric("max_drawdown", drawdown)

    def _update_drawdown(self) -> None:
        """Update drawdown calculation based on current P&L."""
        # This is a simplified drawdown calculation
        # In practice, you'd want to track peak balance over time
        current_pnl = self.trade_metrics["total_pnl"]

        # Find recent peak P&L
        pnl_metrics = self.performance_metrics.get("total_pnl", deque())
        if pnl_metrics:
            peak_pnl = max(metric.value for metric in pnl_metrics)
            if peak_pnl > 0:
                drawdown = max(0, (peak_pnl - current_pnl) / peak_pnl)
                self.update_max_drawdown(drawdown)

    async def _check_alerts(self) -> None:
        """Check alert conditions and trigger callbacks."""
        try:
            alerts = []

            # Check system metrics
            if self.system_metrics:
                latest = self.system_metrics[-1]

                if latest.cpu_percent > self.alert_thresholds["cpu_percent"]:
                    alerts.append(f"High CPU usage: {latest.cpu_percent:.1f}%")

                if latest.memory_percent > self.alert_thresholds["memory_percent"]:
                    alerts.append(f"High memory usage: {latest.memory_percent:.1f}%")

                if latest.disk_percent > self.alert_thresholds["disk_percent"]:
                    alerts.append(f"High disk usage: {latest.disk_percent:.1f}%")

            # Check API latencies
            for endpoint, latencies in self.api_latencies.items():
                if latencies:
                    avg_latency = statistics.mean(latencies)
                    if avg_latency > self.alert_thresholds["api_latency_ms"]:
                        alerts.append(
                            f"High API latency for {endpoint}: {avg_latency:.1f}ms"
                        )

            # Check consecutive errors
            if (
                self.trade_metrics["consecutive_errors"]
                > self.alert_thresholds["consecutive_errors"]
            ):
                alerts.append(
                    f"Too many consecutive errors: {self.trade_metrics['consecutive_errors']}"
                )

            # Check max drawdown
            if (
                self.trade_metrics["max_drawdown"]
                > self.alert_thresholds["max_drawdown"]
            ):
                alerts.append(
                    f"High drawdown: {self.trade_metrics['max_drawdown']:.1%}"
                )

            # Trigger alert callbacks
            if alerts:
                await self._trigger_alerts(alerts)

        except Exception as e:
            logger.error(f"Error checking alerts: {e}")

    async def _trigger_alerts(self, alerts: list[str]) -> None:
        """Trigger registered alert callbacks."""
        for alert in alerts:
            logger.warning(f"ALERT: {alert}")

            for callback in self.alert_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(alert)
                    else:
                        callback(alert)
                except Exception as e:
                    logger.error(f"Error in alert callback: {e}")

    def add_alert_callback(self, callback: Callable) -> None:
        """Add alert callback function."""
        self.alert_callbacks.append(callback)

    def get_performance_summary(self) -> dict[str, Any]:
        """Get comprehensive performance summary."""
        uptime = datetime.utcnow() - self.start_time

        summary = {
            "uptime_seconds": uptime.total_seconds(),
            "uptime_formatted": str(uptime).split(".")[0],  # Remove microseconds
            "trade_metrics": self.trade_metrics.copy(),
            "system_status": self._get_current_system_status(),
            "api_performance": self._get_api_performance_summary(),
            "recent_metrics": self._get_recent_metrics_summary(),
        }

        return summary

    def _get_current_system_status(self) -> dict[str, Any]:
        """Get current system resource status."""
        if not self.system_metrics:
            return {}

        latest = self.system_metrics[-1]
        return {
            "cpu_percent": latest.cpu_percent,
            "memory_percent": latest.memory_percent,
            "memory_usage_mb": latest.memory_usage_mb,
            "disk_percent": latest.disk_percent,
            "disk_usage_gb": latest.disk_usage_gb,
            "timestamp": latest.timestamp.isoformat(),
        }

    def _get_api_performance_summary(self) -> dict[str, dict[str, float]]:
        """Get API performance summary."""
        summary = {}

        for endpoint, latencies in self.api_latencies.items():
            if latencies:
                summary[endpoint] = {
                    "avg_latency_ms": statistics.mean(latencies),
                    "min_latency_ms": min(latencies),
                    "max_latency_ms": max(latencies),
                    "median_latency_ms": statistics.median(latencies),
                    "call_count": len(latencies),
                }

        return summary

    def _get_recent_metrics_summary(self) -> dict[str, dict[str, float]]:
        """Get summary of recent custom metrics."""
        summary = {}

        for metric_name, metrics in self.performance_metrics.items():
            if metrics:
                values = [m.value for m in metrics]
                summary[metric_name] = {
                    "current": values[-1],
                    "avg": statistics.mean(values),
                    "min": min(values),
                    "max": max(values),
                    "count": len(values),
                }

        return summary

    async def get_daily_pnl(self) -> float:
        """Get daily P&L from metrics."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        total_pnl_metrics = self.performance_metrics.get("total_pnl", deque())

        # Find metrics from today
        daily_metrics = [m for m in total_pnl_metrics if m.timestamp >= today]

        if daily_metrics:
            # Return the change from start of day
            start_pnl = daily_metrics[0].value
            current_pnl = daily_metrics[-1].value
            return current_pnl - start_pnl

        return 0.0

    async def get_max_drawdown(self) -> float:
        """Get maximum drawdown."""
        return self.trade_metrics["max_drawdown"]

    def export_metrics(
        self,
        include_system: bool = True,
        include_custom: bool = True,
        include_api: bool = True,
    ) -> dict[str, Any]:
        """Export all metrics data."""
        export_data = {
            "export_timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
            "trade_metrics": self.trade_metrics.copy(),
        }

        if include_system and self.system_metrics:
            export_data["system_metrics"] = [
                {
                    "timestamp": m.timestamp.isoformat(),
                    "cpu_percent": m.cpu_percent,
                    "memory_percent": m.memory_percent,
                    "memory_usage_mb": m.memory_usage_mb,
                    "disk_percent": m.disk_percent,
                    "disk_usage_gb": m.disk_usage_gb,
                    "network_sent_mb": m.network_sent_mb,
                    "network_recv_mb": m.network_recv_mb,
                }
                for m in self.system_metrics
            ]

        if include_custom:
            export_data["custom_metrics"] = {}
            for name, metrics in self.performance_metrics.items():
                export_data["custom_metrics"][name] = [
                    {
                        "timestamp": m.timestamp.isoformat(),
                        "value": m.value,
                        "metadata": m.metadata,
                    }
                    for m in metrics
                ]

        if include_api:
            export_data["api_latencies"] = {
                endpoint: list(latencies)
                for endpoint, latencies in self.api_latencies.items()
            }

        return export_data


class PerformanceTracker:
    """
    Performance tracking utility for individual operations.
    """

    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics = metrics_collector

    def time_operation(self, operation_name: str):
        """Context manager to time an operation."""
        return TimedOperation(operation_name, self.metrics)

    async def track_async_operation(
        self, operation_name: str, operation_func, *args, **kwargs
    ):
        """Track an async operation's execution time."""
        start_time = time.time()

        try:
            result = await operation_func(*args, **kwargs)
            success = True
            return result
        except Exception as e:
            success = False
            raise e
        finally:
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_metric(
                f"{operation_name}_duration_ms", duration_ms, {"success": success}
            )


class TimedOperation:
    """Context manager for timing operations."""

    def __init__(self, operation_name: str, metrics_collector: MetricsCollector):
        self.operation_name = operation_name
        self.metrics = metrics_collector
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            success = exc_type is None

            self.metrics.record_metric(
                f"{self.operation_name}_duration_ms", duration_ms, {"success": success}
            )


__all__ = [
    "MetricsCollector",
    "PerformanceTracker",
    "PerformanceMetric",
    "SystemMetrics",
    "TimedOperation",
]
