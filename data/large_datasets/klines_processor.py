"""
Large Klines Dataset Processor

Handles processing of massive klines CSV files (like your 7GB klines_v14_0.csv)
with memory-efficient chunked processing and intelligent caching.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List, Iterator, Tuple, Any
import logging
from datetime import datetime, timedelta
import pickle
import gzip
import json
from dataclasses import dataclass, asdict
import hashlib
import time

logger = logging.getLogger(__name__)


@dataclass
class KlinesMetadata:
    """Metadata about a klines dataset."""
    filename: str
    total_rows: int
    date_range_start: str
    date_range_end: str
    symbols: List[str]
    timeframes: List[str] 
    file_size_mb: float
    columns: List[str]
    created_at: str
    processing_time_seconds: float


class LargeKlinesProcessor:
    """
    Processes large klines CSV files with memory efficiency.
    
    Features:
    - Chunked processing for files of any size
    - In-memory caching of frequently used data
    - Smart sampling for ML training
    - Data validation and cleaning
    - Multiple output formats
    """
    
    def __init__(self, cache_dir: str = "data/cache", memory_limit_mb: int = 1000):
        """
        Initialize processor.
        
        Args:
            cache_dir: Directory for caching processed data
            memory_limit_mb: Max memory usage for caching (MB)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.memory_limit_mb = memory_limit_mb
        self.memory_cache: Dict[str, pd.DataFrame] = {}
        self.cache_usage_mb = 0
        self.cache_access_times: Dict[str, float] = {}
        
        # Processing stats
        self.stats = {
            'files_processed': 0,
            'total_rows_processed': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    def analyze_file(self, filepath: str, sample_size: int = 10000) -> KlinesMetadata:
        """
        Analyze a large klines file without loading it entirely.
        
        Args:
            filepath: Path to the CSV file
            sample_size: Number of rows to sample for analysis
            
        Returns:
            KlinesMetadata object with file information
        """
        start_time = time.time()
        filepath = Path(filepath)
        
        logger.info(f"Analyzing large file: {filepath} ({filepath.stat().st_size / 1024**3:.2f} GB)")
        
        # Get file size
        file_size_mb = filepath.stat().st_size / (1024 * 1024)
        
        # Read header and sample
        sample_df = pd.read_csv(filepath, nrows=sample_size)
        
        # Count total rows (memory efficient)
        total_rows = sum(1 for _ in open(filepath)) - 1  # -1 for header
        
        # Analyze date range
        if 'timestamp' in sample_df.columns:
            sample_df['timestamp'] = pd.to_datetime(sample_df['timestamp'])
            date_start = sample_df['timestamp'].min().isoformat()
            
            # Get last few rows for end date
            tail_df = pd.read_csv(filepath, skiprows=max(0, total_rows - 1000), nrows=1000)
            if 'timestamp' in tail_df.columns:
                tail_df['timestamp'] = pd.to_datetime(tail_df['timestamp'])
                date_end = tail_df['timestamp'].max().isoformat()
            else:
                date_end = date_start
        else:
            date_start = "Unknown"
            date_end = "Unknown"
        
        # Extract symbols and timeframes if available
        symbols = []
        timeframes = []
        
        if 'symbol' in sample_df.columns:
            symbols = sorted(sample_df['symbol'].unique().tolist())
        
        if 'timeframe' in sample_df.columns:
            timeframes = sorted(sample_df['timeframe'].unique().tolist())
        
        processing_time = time.time() - start_time
        
        metadata = KlinesMetadata(
            filename=filepath.name,
            total_rows=total_rows,
            date_range_start=date_start,
            date_range_end=date_end,
            symbols=symbols,
            timeframes=timeframes,
            file_size_mb=file_size_mb,
            columns=sample_df.columns.tolist(),
            created_at=datetime.now().isoformat(),
            processing_time_seconds=processing_time
        )
        
        # Save metadata
        metadata_file = self.cache_dir / f"{filepath.stem}_metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(asdict(metadata), f, indent=2)
        
        logger.info(f"Analysis complete: {total_rows:,} rows, {len(symbols)} symbols, "
                   f"{len(timeframes)} timeframes in {processing_time:.2f}s")
        
        return metadata
    
    def load_chunk_iterator(self, 
                           filepath: str, 
                           chunk_size: int = 10000,
                           symbol_filter: Optional[str] = None,
                           date_filter: Optional[Tuple[str, str]] = None) -> Iterator[pd.DataFrame]:
        """
        Create iterator for processing large file in chunks.
        
        Args:
            filepath: Path to CSV file
            chunk_size: Rows per chunk
            symbol_filter: Optional symbol to filter (e.g., 'BTCUSDT')
            date_filter: Optional date range tuple (start, end)
            
        Yields:
            DataFrame chunks
        """
        logger.info(f"Loading {filepath} in chunks of {chunk_size:,} rows")
        
        chunk_count = 0
        total_rows = 0
        
        for chunk in pd.read_csv(filepath, chunksize=chunk_size):
            chunk_count += 1
            
            # Apply filters
            if symbol_filter and 'symbol' in chunk.columns:
                chunk = chunk[chunk['symbol'] == symbol_filter]
            
            if date_filter and 'timestamp' in chunk.columns:
                chunk['timestamp'] = pd.to_datetime(chunk['timestamp'])
                start_date, end_date = date_filter
                chunk = chunk[
                    (chunk['timestamp'] >= start_date) & 
                    (chunk['timestamp'] <= end_date)
                ]
            
            if len(chunk) > 0:
                total_rows += len(chunk)
                
                if chunk_count % 100 == 0:
                    logger.info(f"Processed {chunk_count} chunks, {total_rows:,} total rows")
                
                yield chunk
        
        logger.info(f"Chunk processing complete: {chunk_count} chunks, {total_rows:,} rows")
    
    def create_training_sample(self,
                              filepath: str,
                              output_file: str,
                              sample_ratio: float = 0.01,
                              symbol: Optional[str] = None,
                              strategy: str = 'random') -> pd.DataFrame:
        """
        Create a training sample from large dataset.
        
        Args:
            filepath: Path to large CSV
            output_file: Path to save sample
            sample_ratio: Fraction of data to sample (0.01 = 1%)
            symbol: Optional symbol filter
            strategy: Sampling strategy ('random', 'systematic', 'recent')
            
        Returns:
            Sampled DataFrame
        """
        logger.info(f"Creating {sample_ratio*100:.1f}% training sample with '{strategy}' strategy")
        
        # Calculate chunk parameters
        total_rows = sum(1 for _ in open(filepath)) - 1
        sample_size = int(total_rows * sample_ratio)
        
        logger.info(f"Target sample size: {sample_size:,} from {total_rows:,} rows")
        
        chunks = []
        rows_collected = 0
        
        if strategy == 'random':
            # Random sampling across chunks
            chunk_sample_ratio = sample_ratio
            
            for chunk in self.load_chunk_iterator(filepath, symbol_filter=symbol):
                chunk_sample = chunk.sample(
                    n=min(len(chunk), int(len(chunk) * chunk_sample_ratio)),
                    replace=False
                )
                chunks.append(chunk_sample)
                rows_collected += len(chunk_sample)
                
                if rows_collected >= sample_size:
                    break
        
        elif strategy == 'systematic':
            # Every Nth row
            step = max(1, int(1 / sample_ratio))
            
            for chunk in self.load_chunk_iterator(filepath, symbol_filter=symbol):
                systematic_sample = chunk.iloc[::step]
                chunks.append(systematic_sample)
                rows_collected += len(systematic_sample)
                
                if rows_collected >= sample_size:
                    break
        
        elif strategy == 'recent':
            # Most recent data
            skip_rows = max(0, total_rows - sample_size)
            recent_df = pd.read_csv(filepath, skiprows=skip_rows)
            
            if symbol and 'symbol' in recent_df.columns:
                recent_df = recent_df[recent_df['symbol'] == symbol]
            
            chunks = [recent_df]
            rows_collected = len(recent_df)
        
        # Combine chunks
        if chunks:
            sample_df = pd.concat(chunks, ignore_index=True)
            
            # Final size adjustment
            if len(sample_df) > sample_size:
                sample_df = sample_df.sample(n=sample_size, replace=False).reset_index(drop=True)
            
            # Save sample
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save in multiple formats
            sample_df.to_csv(output_path, index=False)
            sample_df.to_parquet(output_path.with_suffix('.parquet'), index=False)
            
            logger.info(f"Training sample saved: {len(sample_df):,} rows to {output_path}")
            
            # Cache in memory if small enough
            cache_key = f"sample_{output_path.stem}"
            self._add_to_cache(cache_key, sample_df)
            
            return sample_df
        
        else:
            logger.warning("No data collected for training sample")
            return pd.DataFrame()
    
    def prepare_ml_features(self,
                           data: pd.DataFrame,
                           feature_config: Optional[Dict] = None) -> Dict[str, np.ndarray]:
        """
        Prepare features for machine learning from klines data.
        
        Args:
            data: DataFrame with OHLCV data
            feature_config: Configuration for feature engineering
            
        Returns:
            Dictionary of feature arrays
        """
        if feature_config is None:
            feature_config = {
                'price_features': True,
                'technical_indicators': True,
                'volume_features': True,
                'time_features': True,
                'sequence_length': 30
            }
        
        features = {}
        
        # Ensure required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in data.columns for col in required_cols):
            raise ValueError(f"Missing required columns: {required_cols}")
        
        # Price features
        if feature_config.get('price_features', True):
            features['ohlc'] = data[['open', 'high', 'low', 'close']].values
            features['returns'] = data['close'].pct_change().fillna(0).values
            features['log_returns'] = np.log(data['close'] / data['close'].shift(1)).fillna(0).values
        
        # Volume features
        if feature_config.get('volume_features', True):
            features['volume'] = data['volume'].values
            features['volume_ma'] = data['volume'].rolling(20).mean().fillna(data['volume']).values
            features['vwap'] = ((data['close'] * data['volume']).cumsum() / data['volume'].cumsum()).fillna(data['close']).values
        
        # Technical indicators (basic ones)
        if feature_config.get('technical_indicators', True):
            # Simple moving averages
            features['sma_20'] = data['close'].rolling(20).mean().fillna(data['close']).values
            features['sma_50'] = data['close'].rolling(50).mean().fillna(data['close']).values
            
            # RSI approximation
            delta = data['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            features['rsi'] = (100 - (100 / (1 + rs))).fillna(50).values
            
            # Bollinger Bands
            bb_sma = data['close'].rolling(20).mean()
            bb_std = data['close'].rolling(20).std()
            features['bb_upper'] = (bb_sma + 2 * bb_std).fillna(data['close']).values
            features['bb_lower'] = (bb_sma - 2 * bb_std).fillna(data['close']).values
        
        # Time features
        if feature_config.get('time_features', True) and 'timestamp' in data.columns:
            if data['timestamp'].dtype == 'object':
                data['timestamp'] = pd.to_datetime(data['timestamp'])
            
            features['hour'] = data['timestamp'].dt.hour.values
            features['day_of_week'] = data['timestamp'].dt.dayofweek.values
            features['month'] = data['timestamp'].dt.month.values
        
        # Create sequences for LSTM
        seq_len = feature_config.get('sequence_length', 30)
        if seq_len > 1:
            sequences = {}
            for key, values in features.items():
                if len(values.shape) == 1:  # 1D arrays
                    sequences[f'{key}_seq'] = self._create_sequences(values, seq_len)
                elif len(values.shape) == 2:  # 2D arrays
                    sequences[f'{key}_seq'] = self._create_sequences_2d(values, seq_len)
            features.update(sequences)
        
        logger.info(f"Prepared ML features: {list(features.keys())}")
        return features
    
    def _create_sequences(self, data: np.ndarray, seq_length: int) -> np.ndarray:
        """Create sequences for time series ML."""
        sequences = []
        for i in range(len(data) - seq_length + 1):
            sequences.append(data[i:i + seq_length])
        return np.array(sequences)
    
    def _create_sequences_2d(self, data: np.ndarray, seq_length: int) -> np.ndarray:
        """Create sequences for 2D data."""
        sequences = []
        for i in range(len(data) - seq_length + 1):
            sequences.append(data[i:i + seq_length])
        return np.array(sequences)
    
    def _add_to_cache(self, key: str, data: pd.DataFrame):
        """Add data to memory cache with size management."""
        data_size_mb = data.memory_usage(deep=True).sum() / (1024 * 1024)
        
        # Check if cache would exceed limit
        if self.cache_usage_mb + data_size_mb > self.memory_limit_mb:
            self._evict_cache()
        
        # Add to cache
        self.memory_cache[key] = data.copy()
        self.cache_usage_mb += data_size_mb
        self.cache_access_times[key] = time.time()
        
        logger.debug(f"Added {key} to cache ({data_size_mb:.1f} MB), "
                    f"total usage: {self.cache_usage_mb:.1f} MB")
    
    def _evict_cache(self):
        """Evict least recently used items from cache."""
        if not self.memory_cache:
            return
        
        # Sort by access time (oldest first)
        sorted_items = sorted(self.cache_access_times.items(), key=lambda x: x[1])
        
        # Remove oldest items until under 75% of limit
        target_mb = self.memory_limit_mb * 0.75
        
        for key, _ in sorted_items:
            if self.cache_usage_mb <= target_mb:
                break
            
            if key in self.memory_cache:
                data_size = self.memory_cache[key].memory_usage(deep=True).sum() / (1024 * 1024)
                del self.memory_cache[key]
                del self.cache_access_times[key]
                self.cache_usage_mb -= data_size
                
                logger.debug(f"Evicted {key} from cache ({data_size:.1f} MB)")
    
    def get_cached_data(self, key: str) -> Optional[pd.DataFrame]:
        """Get data from cache."""
        if key in self.memory_cache:
            self.cache_access_times[key] = time.time()
            self.stats['cache_hits'] += 1
            return self.memory_cache[key].copy()
        
        self.stats['cache_misses'] += 1
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processor statistics."""
        return {
            **self.stats,
            'cache_size_mb': self.cache_usage_mb,
            'cached_items': len(self.memory_cache),
            'memory_limit_mb': self.memory_limit_mb
        }
    
    def clear_cache(self):
        """Clear all cached data."""
        self.memory_cache.clear()
        self.cache_access_times.clear()
        self.cache_usage_mb = 0
        logger.info("Memory cache cleared")


def create_processor(cache_dir: str = "data/cache", memory_limit_mb: int = 1000) -> LargeKlinesProcessor:
    """Create a configured klines processor."""
    return LargeKlinesProcessor(cache_dir=cache_dir, memory_limit_mb=memory_limit_mb)