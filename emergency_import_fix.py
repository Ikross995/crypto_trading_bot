#!/usr/bin/env python3
"""
Emergency fix for SignalType import issue
"""

import os
import sys
import shutil
from pathlib import Path

def fix_import_cache():
    """Clear Python cache and fix imports"""
    print("🧹 Emergency import cache cleanup...")
    
    # Clear Python cache
    import glob
    cache_dirs = glob.glob('**/__pycache__', recursive=True)
    for cache_dir in cache_dirs:
        try:
            shutil.rmtree(cache_dir)
            print(f"✅ Cleared {cache_dir}")
        except:
            pass
            
    # Clear .pyc files
    pyc_files = glob.glob('**/*.pyc', recursive=True)
    for pyc_file in pyc_files:
        try:
            os.remove(pyc_file)
        except:
            pass
            
    print(f"🧹 Cleared {len(cache_dirs)} cache dirs and {len(pyc_files)} .pyc files")
    
    # Test imports
    print("🧪 Testing critical imports...")
    try:
        from core.constants import SignalType, PositionSide, TradingMode
        print("✅ core.constants imports working")
        
        from exchange.client import create_client, BinanceMarketDataClient
        print("✅ exchange.client imports working")
        
        from runner.paper import PaperTradingEngine
        print("✅ runner.paper imports working")
        
        print("🎉 All imports successful after cache clear!")
        return True
        
    except ImportError as e:
        print(f"❌ Import still failing: {e}")
        
        # Additional fix - ensure constants are properly available
        constants_content = '''"""
Core constants for AI Trading Bot - Emergency Fix
"""

from enum import Enum


class TradingMode(Enum):
    """Trading execution modes."""
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


class OrderSide(Enum):
    """Order side directions."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class PositionSide(Enum):
    """Position sides for futures trading."""
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"


class SignalType(Enum):
    """Trading signal types."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class ExitReason(Enum):
    """Reasons for position exits."""
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    SIGNAL_REVERSE = "SIGNAL_REVERSE"
    RISK_MANAGEMENT = "RISK_MANAGEMENT"
    MANUAL = "MANUAL"


# Explicit exports for better compatibility
__all__ = [
    "TradingMode",
    "OrderSide", 
    "OrderType",
    "PositionSide",
    "SignalType",
    "ExitReason",
]
'''
        
        # Backup and recreate constants.py
        constants_file = Path("core/constants.py")
        if constants_file.exists():
            shutil.copy(constants_file, constants_file.with_suffix('.py.backup'))
            
        with open(constants_file, 'w', encoding='utf-8') as f:
            f.write(constants_content)
            
        print("✅ Recreated core/constants.py")
        return False

if __name__ == "__main__":
    fix_import_cache()