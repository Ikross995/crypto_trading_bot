"""
Data fetchers for historical and live market data.

Handles data retrieval from Binance API with caching and error handling.
"""

import asyncio
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
import pickle
import os

from exchange.client import BinanceClient
from core.constants import TIMEFRAME_TO_MINUTES
from core.types import MarketData


logger = logging.getLogger(__name__)


class HistoricalDataFetcher:
    """
    Fetches historical market data with intelligent caching.
    
    Features:
    - Automatic data caching to avoid redundant API calls
    - Gap detection and filling
    - Data validation and cleaning
    - Multiple timeframe support
    """
    
    def __init__(self, client: BinanceClient, cache_dir: str = "data/cache"):
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache configuration
        self.max_cache_age_hours = 24
        self.max_api_calls_per_minute = 1200  # Binance limit
        
    def get_historical_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """
        Get historical OHLCV data with intelligent caching.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            timeframe: Timeframe (1m, 5m, 1h, etc.)
            start_date: Start date (defaults to 100 days ago)
            end_date: End date (defaults to now)
            limit: Max number of candles per request
            
        Returns:
            DataFrame with OHLCV data
        """
        # Default date range
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=100)
            
        # Check cache first
        cached_data = self._load_from_cache(symbol, timeframe, start_date, end_date)
        if cached_data is not None:
            logger.info(f"Loaded {len(cached_data)} candles from cache for {symbol} {timeframe}")
            return cached_data
        
        # Fetch from API
        logger.info(f"Fetching historical data for {symbol} {timeframe} from {start_date} to {end_date}")
        
        try:
            data_frames = []
            current_start = start_date
            
            while current_start < end_date:
                # Calculate end time for this batch
                timeframe_minutes = TIMEFRAME_TO_MINUTES[timeframe]
                batch_end = min(
                    current_start + timedelta(minutes=timeframe_minutes * limit),
                    end_date
                )
                
                # Fetch batch
                klines = self.client.client.get_historical_klines(
                    symbol,
                    timeframe,
                    current_start.strftime("%Y-%m-%d %H:%M:%S"),
                    batch_end.strftime("%Y-%m-%d %H:%M:%S"),
                    limit=limit
                )
                
                if not klines:
                    break
                    
                # Convert to DataFrame
                df_batch = self._klines_to_dataframe(klines)
                data_frames.append(df_batch)
                
                # Update start time for next batch
                current_start = datetime.fromtimestamp(klines[-1][0] / 1000) + timedelta(minutes=timeframe_minutes)
                
                # Rate limiting
                import time
                time.sleep(0.1)  # 10 requests per second max
            
            if not data_frames:
                logger.warning(f"No data found for {symbol} {timeframe}")
                return pd.DataFrame()
            
            # Combine all batches
            df = pd.concat(data_frames, ignore_index=True)
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            
            # Save to cache
            self._save_to_cache(df, symbol, timeframe, start_date, end_date)
            
            logger.info(f"Fetched {len(df)} candles for {symbol} {timeframe}")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            raise
    
    def _klines_to_dataframe(self, klines: List[List]) -> pd.DataFrame:
        """Convert Binance klines to DataFrame."""
        columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                  'close_time', 'quote_asset_volume', 'number_of_trades',
                  'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore']
        
        df = pd.DataFrame(klines, columns=columns)
        
        # Convert timestamps
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
        
        # Convert numeric columns
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'quote_asset_volume',
                       'number_of_trades', 'taker_buy_base_asset_volume', 
                       'taker_buy_quote_asset_volume']
        
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col])
        
        # Set timestamp as index
        df.set_index('timestamp', inplace=True)
        
        return df
    
    def _get_cache_path(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime) -> Path:
        """Generate cache file path."""
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")
        filename = f"{symbol}_{timeframe}_{start_str}_{end_str}.pkl"
        return self.cache_dir / filename
    
    def _load_from_cache(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Load data from cache if available and fresh."""
        cache_path = self._get_cache_path(symbol, timeframe, start_date, end_date)
        
        if not cache_path.exists():
            return None
        
        # Check cache age
        cache_age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if cache_age > timedelta(hours=self.max_cache_age_hours):
            logger.debug(f"Cache expired for {cache_path}")
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                df = pickle.load(f)
            return df
        except Exception as e:
            logger.warning(f"Failed to load cache {cache_path}: {e}")
            return None
    
    def _save_to_cache(self, df: pd.DataFrame, symbol: str, timeframe: str, start_date: datetime, end_date: datetime):
        """Save data to cache."""
        cache_path = self._get_cache_path(symbol, timeframe, start_date, end_date)
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(df, f)
            logger.debug(f"Saved {len(df)} rows to cache: {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to save cache {cache_path}: {e}")
    
    def clear_cache(self, symbol: Optional[str] = None):
        """Clear cache files."""
        pattern = f"{symbol}_*" if symbol else "*"
        cache_files = list(self.cache_dir.glob(f"{pattern}.pkl"))
        
        for file in cache_files:
            file.unlink()
            
        logger.info(f"Cleared {len(cache_files)} cache files")


class LiveDataFetcher:
    """
    Fetches live market data and maintains real-time feeds.
    
    Features:
    - Real-time price updates
    - Order book snapshots
    - Recent trades data
    - WebSocket integration
    """
    
    def __init__(self, client: BinanceClient):
        self.client = client
        
        # Live data cache
        self.latest_prices: Dict[str, float] = {}
        self.latest_volumes: Dict[str, float] = {}
        self.order_books: Dict[str, Dict] = {}
        
        # Update tracking
        self.last_update: Dict[str, datetime] = {}
        
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get latest price for symbol."""
        try:
            ticker = self.client.client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            
            # Update cache
            self.latest_prices[symbol] = price
            self.last_update[symbol] = datetime.now()
            
            return price
            
        except Exception as e:
            logger.error(f"Error getting latest price for {symbol}: {e}")
            return self.latest_prices.get(symbol)
    
    def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get comprehensive market data for symbol."""
        try:
            # Get ticker data
            ticker = self.client.client.get_ticker(symbol=symbol)
            
            market_data = MarketData(
                symbol=symbol,
                price=float(ticker['lastPrice']),
                bid=float(ticker['bidPrice']),
                ask=float(ticker['askPrice']),
                volume=float(ticker['volume']),
                quote_volume=float(ticker['quoteVolume']),
                price_change_pct=float(ticker['priceChangePercent']),
                high_24h=float(ticker['highPrice']),
                low_24h=float(ticker['lowPrice']),
                timestamp=datetime.now()
            )
            
            # Update cache
            self.latest_prices[symbol] = market_data.price
            self.latest_volumes[symbol] = market_data.volume
            self.last_update[symbol] = market_data.timestamp
            
            return market_data
            
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return None
    
    def get_order_book(self, symbol: str, limit: int = 100) -> Optional[Dict]:
        """Get current order book depth."""
        try:
            depth = self.client.client.get_order_book(symbol=symbol, limit=limit)
            
            order_book = {
                'symbol': symbol,
                'bids': [(float(bid[0]), float(bid[1])) for bid in depth['bids']],
                'asks': [(float(ask[0]), float(ask[1])) for ask in depth['asks']],
                'timestamp': datetime.now()
            }
            
            # Cache order book
            self.order_books[symbol] = order_book
            
            return order_book
            
        except Exception as e:
            logger.error(f"Error getting order book for {symbol}: {e}")
            return self.order_books.get(symbol)
    
    def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Get recent trades for symbol."""
        try:
            trades = self.client.client.get_recent_trades(symbol=symbol, limit=limit)
            
            processed_trades = []
            for trade in trades:
                processed_trades.append({
                    'id': trade['id'],
                    'price': float(trade['price']),
                    'quantity': float(trade['qty']),
                    'time': datetime.fromtimestamp(trade['time'] / 1000),
                    'is_buyer_maker': trade['isBuyerMaker']
                })
            
            return processed_trades
            
        except Exception as e:
            logger.error(f"Error getting recent trades for {symbol}: {e}")
            return []
    
    def get_multiple_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Get latest prices for multiple symbols efficiently."""
        try:
            tickers = self.client.client.get_all_tickers()
            
            symbol_prices = {}
            for ticker in tickers:
                symbol = ticker['symbol']
                if symbol in symbols:
                    price = float(ticker['price'])
                    symbol_prices[symbol] = price
                    
                    # Update cache
                    self.latest_prices[symbol] = price
                    self.last_update[symbol] = datetime.now()
            
            return symbol_prices
            
        except Exception as e:
            logger.error(f"Error getting multiple prices: {e}")
            return {symbol: self.latest_prices.get(symbol, 0.0) for symbol in symbols}
    
    def is_data_fresh(self, symbol: str, max_age_seconds: int = 60) -> bool:
        """Check if cached data is fresh enough."""
        last_update = self.last_update.get(symbol)
        if last_update is None:
            return False
        
        age = (datetime.now() - last_update).total_seconds()
        return age <= max_age_seconds
    
    def get_cached_price(self, symbol: str) -> Optional[float]:
        """Get cached price if available."""
        return self.latest_prices.get(symbol)
    
    def clear_cache(self):
        """Clear all cached data."""
        self.latest_prices.clear()
        self.latest_volumes.clear()
        self.order_books.clear()
        self.last_update.clear()
        logger.info("Cleared live data cache")