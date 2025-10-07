"""
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
