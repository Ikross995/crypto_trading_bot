"""
Sample data loader for testing trading strategies.

Provides utilities to load sample candlestick data for backtesting and strategy development.
"""

import pandas as pd
from pathlib import Path
from typing import Optional

from core.types import MarketData


def load_sample_data(
    symbol: str = "BTCUSDT", 
    timeframe: str = "1m",
    start_rows: Optional[int] = None,
    end_rows: Optional[int] = None
) -> pd.DataFrame:
    """
    Load sample candlestick data for testing.
    
    Args:
        symbol: Trading symbol (BTCUSDT, ETHUSDT)
        timeframe: Timeframe (currently only 1m supported)
        start_rows: Start row index (optional)
        end_rows: End row index (optional)
    
    Returns:
        DataFrame with OHLCV data
    """
    # Sample data path
    data_dir = Path(__file__).parent
    filename = f"{symbol}_{timeframe}_sample.csv"
    filepath = data_dir / filename
    
    if not filepath.exists():
        raise FileNotFoundError(f"Sample data not found: {filepath}")
    
    # Load data
    df = pd.read_csv(filepath)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    
    # Apply row filtering if specified
    if start_rows is not None or end_rows is not None:
        df = df.iloc[start_rows:end_rows]
    
    return df


def get_latest_price(symbol: str = "BTCUSDT") -> float:
    """Get the latest price from sample data."""
    df = load_sample_data(symbol)
    return float(df['close'].iloc[-1])


def get_sample_market_data(symbol: str = "BTCUSDT", rows: int = 30) -> MarketData:
    """
    Get sample market data in MarketData format.
    
    Args:
        symbol: Trading symbol
        rows: Number of recent rows to return
    
    Returns:
        MarketData object with sample data
    """
    df = load_sample_data(symbol, end_rows=rows)
    
    return MarketData(
        symbol=symbol,
        timeframe="1m",
        timestamps=df.index.tolist(),
        open=df['open'].tolist(),
        high=df['high'].tolist(), 
        low=df['low'].tolist(),
        close=df['close'].tolist(),
        volume=df['volume'].tolist()
    )


def get_available_symbols() -> list[str]:
    """Get list of available sample data symbols."""
    data_dir = Path(__file__).parent
    symbols = []
    
    for file in data_dir.glob("*_1m_sample.csv"):
        symbol = file.stem.replace("_1m_sample", "")
        symbols.append(symbol)
    
    return sorted(symbols)


def validate_sample_data() -> dict[str, bool]:
    """
    Validate sample data integrity.
    
    Returns:
        Dictionary with validation results for each symbol
    """
    results = {}
    
    for symbol in get_available_symbols():
        try:
            df = load_sample_data(symbol)
            
            # Basic validations
            checks = {
                'has_data': len(df) > 0,
                'has_required_columns': all(col in df.columns for col in ['open', 'high', 'low', 'close', 'volume']),
                'no_missing_values': not df.isnull().any().any(),
                'high_ge_low': (df['high'] >= df['low']).all(),
                'high_ge_open_close': ((df['high'] >= df['open']) & (df['high'] >= df['close'])).all(),
                'low_le_open_close': ((df['low'] <= df['open']) & (df['low'] <= df['close'])).all(),
                'positive_volume': (df['volume'] > 0).all()
            }
            
            results[symbol] = all(checks.values())
            
        except Exception as e:
            results[symbol] = False
    
    return results


if __name__ == "__main__":
    # Demo usage
    print("Available symbols:", get_available_symbols())
    
    # Validate data
    validation = validate_sample_data()
    print("Validation results:", validation)
    
    # Load sample data
    btc_data = load_sample_data("BTCUSDT", end_rows=10)
    print(f"\nBTC Sample Data (first 10 rows):")
    print(btc_data)
    
    print(f"\nLatest BTC price: ${get_latest_price('BTCUSDT'):,.2f}")
    
    # Get MarketData format
    market_data = get_sample_market_data("BTCUSDT", rows=5)
    print(f"\nMarketData format sample:")
    print(f"Symbol: {market_data.symbol}")
    print(f"Close prices: {market_data.close}")