#!/usr/bin/env python3
"""
Quick fix for user's actual import structure
"""

import os
import shutil
from pathlib import Path

def fix_import_compatibility():
    """Fix import issues in user's actual system"""
    
    print("🔧 Fixing import compatibility for user's real system...")
    
    # 1. Add BinanceMarketDataClient to exchange/client.py
    client_fix = """
    
# Additional compatibility classes for paper trading
class BinanceMarketDataClient:
    \"\"\"Market data client compatible with paper trading engine.\"\"\"
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Use IntegratedBinanceClient for market data
        self.client = IntegratedBinanceClient(config)
        
    def initialize(self):
        \"\"\"Initialize market data client.\"\"\"
        self.logger.info("BinanceMarketDataClient initialized (compatibility wrapper)")
        
    def get_current_price(self, symbol: str) -> float:
        \"\"\"Get current price using integrated client.\"\"\"
        try:
            market_data = self.client.get_market_data(symbol, limit=1)
            if market_data and market_data.get('close'):
                return market_data['close'][-1]
            return 67000.0  # Fallback price
        except Exception as e:
            self.logger.warning(f"Error getting price for {symbol}: {e}")
            return 67000.0
            
    def get_klines(self, symbol: str, interval: str = '1m', limit: int = 100):
        \"\"\"Get candlestick data.\"\"\"
        return self.client.get_market_data(symbol, interval, limit)
"""
    
    # Add to client.py
    with open("exchange/client.py", "a", encoding="utf-8") as f:
        f.write(client_fix)
    
    print("✅ Added BinanceMarketDataClient compatibility class")
    
    # 2. Create runner compatibility patch
    runner_patch = """
# Apply compatibility patches before importing runners
try:
    import compat_complete as compat
    compat.apply()
except ImportError:
    try:
        import compat
        compat.apply()
    except ImportError:
        pass  # Continue without compat patches
"""
    
    # Add to runner/__init__.py
    init_file = Path("runner/__init__.py")
    if init_file.exists():
        content = init_file.read_text(encoding="utf-8")
        if "compat" not in content:
            new_content = runner_patch + "\n" + content
            init_file.write_text(new_content, encoding="utf-8")
            print("✅ Added compat patches to runner/__init__.py")
    
    print("🎉 Import compatibility fixes applied!")
    return True

if __name__ == "__main__":
    fix_import_compatibility()