"""
Tests for sample data loading functionality.
"""

import pytest
import pandas as pd
from pathlib import Path

from data.samples import (
    load_sample_data,
    get_latest_price,
    get_sample_market_data,
    get_available_symbols,
    validate_sample_data
)
from core.types import MarketData


class TestSampleDataLoader:
    """Test sample data loading functionality."""
    
    def test_get_available_symbols(self):
        """Test getting list of available symbols."""
        symbols = get_available_symbols()
        
        assert isinstance(symbols, list)
        assert len(symbols) >= 2
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
    
    def test_load_sample_data_btc(self):
        """Test loading BTC sample data."""
        df = load_sample_data("BTCUSDT")
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert len(df) == 61  # 1 hour of 1m data + initial point
        
        # Check required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        assert all(col in df.columns for col in required_cols)
        
        # Check index is datetime
        assert isinstance(df.index, pd.DatetimeIndex)
        
        # Check data integrity
        assert (df['high'] >= df['low']).all()
        assert (df['volume'] > 0).all()
    
    def test_load_sample_data_eth(self):
        """Test loading ETH sample data."""
        df = load_sample_data("ETHUSDT")
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert len(df) == 61  # 1 hour of 1m data + initial point
        
        # ETH prices should be lower than BTC
        assert df['close'].iloc[-1] < 10000  # ETH typically < $10k
    
    def test_load_sample_data_with_rows(self):
        """Test loading sample data with row limits."""
        df = load_sample_data("BTCUSDT", end_rows=10)
        
        assert len(df) == 10
        assert isinstance(df, pd.DataFrame)
    
    def test_load_sample_data_invalid_symbol(self):
        """Test loading data for invalid symbol."""
        with pytest.raises(FileNotFoundError):
            load_sample_data("INVALID")
    
    def test_get_latest_price(self):
        """Test getting latest price."""
        price = get_latest_price("BTCUSDT")
        
        assert isinstance(price, float)
        assert price > 0
        assert 30000 <= price <= 100000  # Reasonable BTC price range
    
    def test_get_sample_market_data(self):
        """Test getting data in MarketData format."""
        market_data = get_sample_market_data("BTCUSDT", rows=5)
        
        assert isinstance(market_data, MarketData)
        assert market_data.symbol == "BTCUSDT"
        assert market_data.price > 0
        assert market_data.bid > 0
        assert market_data.ask > 0
        assert market_data.volume > 0
        assert market_data.bid < market_data.price < market_data.ask
        
        # Check data integrity
        for i in range(len(market_data.close)):
            assert market_data.high[i] >= market_data.low[i]
            assert market_data.high[i] >= market_data.open[i]
            assert market_data.high[i] >= market_data.close[i]
            assert market_data.low[i] <= market_data.open[i]
            assert market_data.low[i] <= market_data.close[i]
            assert market_data.volume[i] > 0
    
    def test_validate_sample_data(self):
        """Test sample data validation."""
        validation = validate_sample_data()
        
        assert isinstance(validation, dict)
        assert len(validation) >= 2
        
        # All available symbols should validate successfully
        for symbol, is_valid in validation.items():
            assert is_valid, f"Sample data for {symbol} failed validation"
    
    def test_data_file_existence(self):
        """Test that sample data files exist."""
        data_dir = Path(__file__).parent.parent / "data" / "samples"
        
        btc_file = data_dir / "BTCUSDT_1m_sample.csv"
        eth_file = data_dir / "ETHUSDT_1m_sample.csv"
        
        assert btc_file.exists(), "BTC sample data file not found"
        assert eth_file.exists(), "ETH sample data file not found"
    
    def test_data_consistency(self):
        """Test data consistency across symbols."""
        btc_data = load_sample_data("BTCUSDT")
        eth_data = load_sample_data("ETHUSDT")
        
        # Both datasets should have same length
        assert len(btc_data) == len(eth_data)
        
        # Both should have same timestamp range
        assert btc_data.index[0] == eth_data.index[0]
        assert btc_data.index[-1] == eth_data.index[-1]
        
        # BTC should generally be more expensive than ETH
        assert btc_data['close'].mean() > eth_data['close'].mean()
    
    def test_price_trends(self):
        """Test that sample data shows realistic price trends."""
        df = load_sample_data("BTCUSDT")
        
        # Check that prices are in reasonable range
        assert df['close'].min() > 30000
        assert df['close'].max() < 100000
        
        # Check that price movement is reasonable (no extreme jumps)
        price_changes = df['close'].pct_change().abs()
        max_change = price_changes.max()
        assert max_change < 0.05  # Max 5% change per minute (very conservative)
        
        # Check volume is positive
        assert (df['volume'] > 0).all()