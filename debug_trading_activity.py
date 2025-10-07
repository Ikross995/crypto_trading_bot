#!/usr/bin/env python3
"""
Debug Trading Activity - Find Why Bot Generates Signals But No Trades

This script helps diagnose why the bot generates signals every second
but doesn't execute any trades.
"""

import os
from dotenv import load_dotenv

def check_current_settings():
    """Check the current .env settings that affect trading."""
    
    # Load environment variables
    load_dotenv()
    
    print("🔍 Current Trading Settings Analysis")
    print("=" * 50)
    
    # Key settings that affect trade execution
    key_settings = {
        'MIN_ADX': 'Minimum ADX for signals (lower = more signals)',
        'BT_CONF_MIN': 'Minimum confidence for trades (lower = more trades)', 
        'COOLDOWN_SEC': 'Cooldown between trades (lower = more frequent)',
        'ANTI_FLIP_SEC': 'Anti-flip cooldown (lower = faster direction changes)',
        'RISK_PER_TRADE_PCT': 'Risk per trade %',
        'VWAP_BAND_PCT': 'VWAP band width (higher = more opportunities)',
        'BT_BBW_MIN': 'Bollinger band width minimum',
        'DCA_DISABLE_ON_TREND': 'Whether DCA is disabled in trends'
    }
    
    print("📊 Key Settings:")
    for key, description in key_settings.items():
        value = os.getenv(key, 'NOT SET')
        print(f"  {key}: {value} ({description})")
    
    print("\n🎯 For Maximum Trading Activity, You Should See:")
    print("  MIN_ADX: 15.0 or lower")
    print("  BT_CONF_MIN: 0.75 or lower") 
    print("  COOLDOWN_SEC: 180 or lower")
    print("  RISK_PER_TRADE_PCT: 0.6 or higher")
    print("  VWAP_BAND_PCT: 0.008 or higher")
    print("  DCA_DISABLE_ON_TREND: false")
    
    # Check if aggressive profile is loaded
    min_adx = float(os.getenv('MIN_ADX', '25.0'))
    bt_conf = float(os.getenv('BT_CONF_MIN', '0.80'))
    cooldown = int(os.getenv('COOLDOWN_SEC', '300'))
    
    print("\n🚨 Diagnosis:")
    if min_adx <= 15.0:
        print("  ✅ MIN_ADX is aggressive")
    else:
        print(f"  ❌ MIN_ADX too high ({min_adx}) - should be 15.0 or lower")
        
    if bt_conf <= 0.75:
        print("  ✅ BT_CONF_MIN is aggressive")
    else:
        print(f"  ❌ BT_CONF_MIN too high ({bt_conf}) - should be 0.75 or lower")
        
    if cooldown <= 180:
        print("  ✅ COOLDOWN_SEC is aggressive")
    else:
        print(f"  ❌ COOLDOWN_SEC too high ({cooldown}) - should be 180 or lower")


def create_ultra_aggressive_env():
    """Create ultra-aggressive settings for maximum trading."""
    
    ultra_settings = """# ULTRA AGGRESSIVE TRADING PROFILE - MAXIMUM ACTIVITY
MODE=paper
DRY_RUN=true
TESTNET=true
SYMBOL=BTCUSDT
SYMBOLS=BTCUSDT,ETHUSDT
TIMEFRAME=1m
LEVERAGE=5

# ULTRA LOW THRESHOLDS FOR MAXIMUM SIGNALS
MIN_ADX=5.0                    # Very low ADX threshold
BT_CONF_MIN=0.30              # Very low confidence threshold  
BT_BBW_MIN=0.0                # No Bollinger Band width requirement
COOLDOWN_SEC=10               # Very short cooldown
ANTI_FLIP_SEC=5               # Very short anti-flip
VWAP_BAND_PCT=0.025           # Very wide VWAP band

# AGGRESSIVE RISK SETTINGS
RISK_PER_TRADE_PCT=1.0        # High risk per trade
MAX_DAILY_LOSS_PCT=10.0       # High daily loss limit
MIN_NOTIONAL_USDT=3.0         # Low minimum for more opportunities

# AGGRESSIVE DCA
DCA_LADDER=-1.0:1.5,-2.5:2.5,-5.0:4.0
ADAPTIVE_DCA=true
DCA_TREND_ADX=3.0             # Very low DCA threshold
DCA_DISABLE_ON_TREND=false    # Allow DCA everywhere

# WIDE STOPS
SL_FIXED_PCT=5.0              # Very wide stops
SL_ATR_MULT=3.0               # Very wide ATR stops  
TP_LEVELS=0.3,0.8,1.5,3.0     # Close profit targets
TP_SHARES=0.4,0.3,0.2,0.1     # Scale out quickly

# FEES
TAKER_FEE=0.0004
MAKER_FEE=0.0002
SLIPPAGE_BPS=2

# API (placeholder)
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_secret_here

# PATHS
KL_PERSIST=data/klines.csv
TRADES_PATH=data/trades.csv
EQUITY_PATH=data/equity.csv
RESULTS_PATH=data/results.csv
STATE_PATH=data/state.json
"""
    
    with open('.env.ultra_debug', 'w') as f:
        f.write(ultra_settings)
    
    print("📝 Created .env.ultra_debug with MAXIMUM aggressive settings")
    print("🚀 To use: cp .env.ultra_debug .env")


def suggest_fixes():
    """Suggest fixes based on current settings."""
    
    print("\n🔧 IMMEDIATE FIXES:")
    print("=" * 30)
    
    print("1. 📊 Check if aggressive profile is loaded:")
    print("   python cli_updated.py config --show")
    
    print("\n2. 🔥 Apply ultra-aggressive settings:")
    print("   cp .env.ultra_debug .env")
    print("   python cli_updated.py config --show")
    
    print("\n3. 🎯 If still no trades, try environment override:")
    print("   MIN_ADX=1.0 BT_CONF_MIN=0.20 COOLDOWN_SEC=5 python cli_updated.py paper --symbols BTCUSDT --verbose")
    
    print("\n4. 🔍 Monitor for specific messages:")
    print("   Look for: 'Signal generated: BUY/SELL' (should appear)")
    print("   Look for: 'Order placed' or 'Position opened' (currently missing)")
    print("   Look for: 'Signal conditions not met' (indicates threshold issues)")


def main():
    """Main diagnostic function."""
    
    print("🔍 TRADING ACTIVITY DEBUG")
    print("=" * 50)
    print("Problem: Bot generates signals every second but no trades occur")
    print("=" * 50)
    
    check_current_settings()
    create_ultra_aggressive_env()
    suggest_fixes()
    
    print("\n" + "=" * 50)
    print("🎯 NEXT STEPS:")
    print("1. Run: cp .env.ultra_debug .env") 
    print("2. Run: python cli_updated.py paper --symbols BTCUSDT --verbose")
    print("3. Watch for 'Order placed' messages within 1-2 minutes")
    print("=" * 50)


if __name__ == "__main__":
    main()