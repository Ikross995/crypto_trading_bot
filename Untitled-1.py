 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/data/__init__.py b/data/__init__.py
index 2c58f529c29044b14f4b1a0af3c9d3b8ad3a5187..bb42aece2b998ae3a50c2092e9d39e1e1b39b525 100644
--- a/data/__init__.py
+++ b/data/__init__.py
@@ -1,21 +1,39 @@
 """Data module for AI Trading Bot."""
 
-from .fetchers import HistoricalDataFetcher, LiveDataFetcher
-from .indicators import TechnicalIndicators
-from .preprocessing import FeatureEngineer
-from .simulator import MarketSimulator, SimulatedMarketData
+from importlib import import_module
+from typing import Any, Dict, List
 
-# Compatibility import (deprecated - use core.constants instead)
-try:
-    from . import constants  # type: ignore
-except ImportError:  # pragma: no cover
-    constants = None
+_ATTR_TO_MODULE: Dict[str, str] = {
+    "HistoricalDataFetcher": ".fetchers",
+    "LiveDataFetcher": ".fetchers",
+    "TechnicalIndicators": ".indicators",
+    "FeatureEngineer": ".preprocessing",
+    "MarketSimulator": ".simulator",
+    "SimulatedMarketData": ".simulator",
+}
 
 __all__ = [
     "HistoricalDataFetcher",
     "LiveDataFetcher",
     "TechnicalIndicators",
     "FeatureEngineer",
     "MarketSimulator",
     "SimulatedMarketData",
+    "constants",
 ]
+
+
+def __getattr__(name: str) -> Any:
+    if name == "constants":
+        return import_module(".constants", __name__)
+
+    try:
+        module = import_module(_ATTR_TO_MODULE[name], __name__)
+    except KeyError as exc:  # pragma: no cover - defensive programming
+        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
+
+    return getattr(module, name)
+
+
+def __dir__() -> List[str]:
+    return sorted(set(__all__ + list(globals().keys())))
 
EOF
)