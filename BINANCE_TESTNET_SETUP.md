# 🚀 Binance Testnet Setup Guide

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
