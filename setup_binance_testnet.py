#!/usr/bin/env python3
"""
Setup Binance Testnet Connection

This script configures the bot to use REAL Binance Testnet API
instead of mock/synthetic data for proper demo trading.
"""

import os
import shutil
from datetime import datetime

def create_testnet_config():
    """Create configuration for Binance Testnet API connection."""
    
    env_content = """# Binance Testnet Configuration for REAL Demo Trading
# Get your testnet API keys from: https://testnet.binance.vision/

# Binance Testnet API Credentials
BINANCE_API_KEY=your_testnet_api_key_here
BINANCE_SECRET_KEY=your_testnet_secret_key_here

# Testnet Settings (DO NOT CHANGE)
BINANCE_TESTNET=true
BINANCE_BASE_URL=https://testnet.binance.vision

# Trading Configuration
TRADING_MODE=paper
USE_MOCK_CLIENT=false
ENABLE_REAL_API=true

# Ultra Aggressive Demo Settings
MIN_SIGNAL_STRENGTH=0.01
FAST_MA_PERIOD=5
SLOW_MA_PERIOD=10
COOLDOWN_SEC=10

# Risk Management
RISK_PER_TRADE=0.01
MAX_DAILY_LOSS=0.1
LEVERAGE=5

# Logging
LOG_LEVEL=DEBUG
ENABLE_API_LOGS=true
"""
    
    # Create testnet environment file
    with open('.env.testnet', 'w', encoding='utf-8') as f:
        f.write(env_content)
    
    print("✅ Created .env.testnet configuration")
    print("   - Binance Testnet API endpoints")
    print("   - Ultra-aggressive trading settings") 
    print("   - Real API integration enabled")


def create_api_setup_guide():
    """Create guide for setting up Binance Testnet API."""
    
    guide_content = """# 🚀 Binance Testnet Setup Guide

## Step 1: Get Testnet API Keys

1. Go to: https://testnet.binance.vision/
2. Click "Login" and sign up with your email
3. Go to API Management
4. Create new API key
5. **IMPORTANT**: Enable "Enable Futures" for futures trading
6. Copy your API Key and Secret Key

## Step 2: Configure Bot

Edit `.env.testnet` file:

```bash
BINANCE_API_KEY=your_actual_api_key_here
BINANCE_SECRET_KEY=your_actual_secret_key_here
```

## Step 3: Test Connection

```bash
# Test with testnet configuration
python cli_updated.py paper --config .env.testnet --symbols BTCUSDT --verbose
```

## Expected Results:

✅ **Real API Connection:**
```
BinanceClient initialized with REAL testnet API
Connected to Binance Testnet: https://testnet.binance.vision
Account balance: 10000.0000 USDT (testnet)
Market data: BTCUSDT prices from real API
```

✅ **Real Price Data:**
```
REAL PRICES - BTCUSDT: fast_ma=67234.52, slow_ma=67235.18, current=67234.56
GENERATED BUY signal for BTCUSDT (strength: 0.80, REAL_PRICE: 67234.5678)
```

## Troubleshooting:

❌ **"Invalid API Key"**: Check your API key is copied correctly
❌ **"Futures not enabled"**: Enable futures trading in API settings  
❌ **"IP restriction"**: Remove IP restrictions in testnet settings

## Benefits of Testnet vs Mock:

- **Real prices** from Binance API
- **Real order execution** (testnet money)
- **Real market conditions** and spreads
- **Actual API latency** and responses
- **Proper testing** of trading strategies

---

**After setup, you'll have a REAL Binance demo trading bot!** 🎯
"""
    
    with open('BINANCE_TESTNET_SETUP.md', 'w', encoding='utf-8') as f:
        f.write(guide_content)
    
    print("✅ Created BINANCE_TESTNET_SETUP.md guide")


def create_real_api_client():
    """Create enhanced client configuration for real API connection."""
    
    client_config = '''"""
Enhanced Binance Client Configuration for Real API Connection

This configuration enables REAL Binance Testnet API instead of mock client.
"""

import os
import logging
from typing import Optional, Dict, Any
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger(__name__)

class RealBinanceClient:
    """Real Binance API client for testnet demo trading."""
    
    def __init__(self, config):
        """Initialize with REAL Binance API connection."""
        self.config = config
        
        # Get API credentials
        api_key = os.getenv('BINANCE_API_KEY')
        secret_key = os.getenv('BINANCE_SECRET_KEY') 
        testnet = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'
        
        if not api_key or not secret_key:
            raise ValueError(
                "Binance API credentials not found! "
                "Please set BINANCE_API_KEY and BINANCE_SECRET_KEY in .env.testnet"
            )
        
        # Initialize REAL Binance client
        self.client = Client(
            api_key=api_key,
            api_secret=secret_key,
            testnet=testnet  # Use testnet for demo trading
        )
        
        logger.info(f"BinanceClient initialized with REAL {'testnet' if testnet else 'mainnet'} API")
        
        # Test connection
        try:
            account_info = self.client.get_account()
            balance = self._get_usdt_balance()
            logger.info(f"Connected to Binance {'Testnet' if testnet else 'Mainnet'}")
            logger.info(f"Account balance: {balance:.4f} USDT ({'testnet' if testnet else 'real'} funds)")
        except Exception as e:
            logger.error(f"Failed to connect to Binance API: {e}")
            raise
    
    def get_market_data(self, symbol: str, interval: str = '1m', limit: int = 100):
        """Get REAL market data from Binance API."""
        try:
            # Get real kline data from Binance
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval, 
                limit=limit
            )
            
            # Parse kline data
            market_data = {
                'symbol': symbol,
                'timestamp': [],
                'open': [],
                'high': [],
                'low': [],
                'close': [],
                'volume': []
            }
            
            for kline in klines:
                market_data['timestamp'].append(kline[0])  # Open time
                market_data['open'].append(float(kline[1]))
                market_data['high'].append(float(kline[2]))
                market_data['low'].append(float(kline[3]))
                market_data['close'].append(float(kline[4]))
                market_data['volume'].append(float(kline[5]))
            
            logger.debug(f"Retrieved {len(klines)} real price points for {symbol}")
            logger.debug(f"Latest price: {market_data['close'][-1]:.4f}")
            
            return market_data
            
        except BinanceAPIException as e:
            logger.error(f"Binance API error getting market data: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting market data: {e}")
            return None
    
    def _get_usdt_balance(self) -> float:
        """Get USDT balance from account."""
        try:
            account = self.client.get_account()
            for balance in account['balances']:
                if balance['asset'] == 'USDT':
                    return float(balance['free'])
            return 0.0
        except Exception:
            return 0.0
    
    def place_test_order(self, symbol: str, side: str, quantity: float):
        """Place test order for demo trading."""
        try:
            # Use test order endpoint for safe demo trading
            result = self.client.create_test_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            logger.info(f"Test order placed: {side} {quantity} {symbol}")
            return result
        except Exception as e:
            logger.error(f"Error placing test order: {e}")
            return None

# Configuration helper
def get_real_api_client(config):
    """Get configured real API client."""
    use_real_api = os.getenv('ENABLE_REAL_API', 'true').lower() == 'true'
    
    if use_real_api:
        return RealBinanceClient(config)
    else:
        # Fallback to mock if requested
        from exchange.client import MockBinanceClient
        return MockBinanceClient(config)
'''
    
    with open('exchange/real_client.py', 'w', encoding='utf-8') as f:
        f.write(client_config)
    
    print("✅ Created exchange/real_client.py")
    print("   - Real Binance API integration")  
    print("   - Testnet demo trading support")
    print("   - Real market data fetching")


def main():
    """Main setup function."""
    
    print("🔧 SETTING UP BINANCE TESTNET CONNECTION")
    print("=" * 60)
    print("Current: Mock client with synthetic data")
    print("Target: Real Binance Testnet API with live prices")
    print("=" * 60)
    
    create_testnet_config()
    create_api_setup_guide() 
    create_real_api_client()
    
    print("\\n" + "=" * 60)
    print("🎯 NEXT STEPS:")
    print("1. Read: BINANCE_TESTNET_SETUP.md")
    print("2. Get API keys from: https://testnet.binance.vision/")
    print("3. Edit .env.testnet with your API credentials")
    print("4. Test: python cli_updated.py paper --config .env.testnet --symbols BTCUSDT")
    print("5. Expect: REAL Binance prices instead of synthetic data")
    print("=" * 60)


if __name__ == "__main__":
    main()