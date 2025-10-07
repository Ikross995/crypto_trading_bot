#!/usr/bin/env python3
"""
Demo script to showcase sample data functionality.

This script demonstrates how to use the sample data for testing trading strategies.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from data.samples import (
    load_sample_data,
    get_latest_price,
    get_sample_market_data,
    get_available_symbols,
    validate_sample_data
)


def main():
    """Main demo function."""
    print("🚀 Crypto Trading Bot - Sample Data Demo")
    print("=" * 50)
    
    # Show available symbols
    print("\n📊 Available Sample Symbols:")
    symbols = get_available_symbols()
    for symbol in symbols:
        print(f"  • {symbol}")
    
    # Validate data
    print("\n✅ Data Validation:")
    validation = validate_sample_data()
    for symbol, is_valid in validation.items():
        status = "✅ Valid" if is_valid else "❌ Invalid"
        print(f"  • {symbol}: {status}")
    
    # Show latest prices
    print("\n💰 Latest Prices:")
    for symbol in symbols:
        try:
            price = get_latest_price(symbol)
            print(f"  • {symbol}: ${price:,.2f}")
        except Exception as e:
            print(f"  • {symbol}: Error - {e}")
    
    # Load and display sample data
    print("\n📈 BTC Sample Data (Last 10 Candles):")
    try:
        btc_data = load_sample_data("BTCUSDT", start_rows=-10)
        print(btc_data[['open', 'high', 'low', 'close', 'volume']].round(2))
    except Exception as e:
        print(f"Error loading BTC data: {e}")
    
    # Show MarketData format
    print("\n🔧 MarketData Format Example (Last 5 candles):")
    try:
        market_data = get_sample_market_data("BTCUSDT", rows=5)
        print(f"Symbol: {market_data.symbol}")
        print(f"Timeframe: {market_data.timeframe}")
        print(f"Close prices: {[round(p, 2) for p in market_data.close]}")
        print(f"Volumes: {[round(v, 2) for v in market_data.volume]}")
    except Exception as e:
        print(f"Error creating MarketData: {e}")
    
    # Show price statistics
    print("\n📊 Price Statistics:")
    for symbol in symbols[:2]:  # Show for first 2 symbols
        try:
            df = load_sample_data(symbol)
            stats = {
                'count': len(df),
                'min': df['close'].min(),
                'max': df['close'].max(),
                'mean': df['close'].mean(),
                'std': df['close'].std(),
                'total_volume': df['volume'].sum()
            }
            
            print(f"\n  {symbol}:")
            print(f"    Candles: {stats['count']}")
            print(f"    Price Range: ${stats['min']:,.2f} - ${stats['max']:,.2f}")
            print(f"    Average: ${stats['mean']:,.2f} ± ${stats['std']:,.2f}")
            print(f"    Total Volume: {stats['total_volume']:,.2f}")
            
        except Exception as e:
            print(f"  {symbol}: Error - {e}")
    
    # Show usage examples
    print("\n💡 Usage Examples:")
    print("""
    # Load sample data
    from data.samples import load_sample_data
    df = load_sample_data("BTCUSDT")
    
    # Get latest price
    from data.samples import get_latest_price
    price = get_latest_price("BTCUSDT")
    
    # Get MarketData format for strategies
    from data.samples import get_sample_market_data
    market_data = get_sample_market_data("BTCUSDT", rows=30)
    
    # Use with technical indicators
    from data.indicators import calculate_sma
    df = load_sample_data("BTCUSDT")
    df['sma_20'] = calculate_sma(df['close'], 20)
    """)
    
    print("\n🎯 Ready for Strategy Testing!")
    print("Use this sample data to test your trading strategies without API calls.")


if __name__ == "__main__":
    main()