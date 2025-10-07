"""
Technical analysis indicators for trading strategies.

Implements common indicators used in cryptocurrency trading with
optimized calculations and proper parameter validation.
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional, Union
import logging

# Import safe numba utilities
from core.utils import jit, HAS_NUMBA


logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """
    Collection of technical analysis indicators.
    
    All methods are static for easy use without instantiation.
    Calculations are optimized with numba where possible.
    """
    
    @staticmethod
    def sma(data: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return data.rolling(window=period).mean()
    
    @staticmethod  
    def ema(data: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return data.ewm(span=period).mean()
    
    @staticmethod
    def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Bollinger Bands indicator.
        
        Returns:
            Tuple of (upper_band, middle_band, lower_band)
        """
        middle_band = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        
        upper_band = middle_band + (std * std_dev)
        lower_band = middle_band - (std * std_dev)
        
        return upper_band, middle_band, lower_band
    
    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        """
        Relative Strength Index.
        
        Args:
            data: Price series (typically close prices)
            period: RSI period (default 14)
            
        Returns:
            RSI values (0-100)
        """
        delta = data.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD (Moving Average Convergence Divergence).
        
        Returns:
            Tuple of (macd_line, signal_line, histogram)
        """
        exp1 = data.ewm(span=fast).mean()
        exp2 = data.ewm(span=slow).mean()
        
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Average True Range.
        
        Args:
            high: High prices
            low: Low prices  
            close: Close prices
            period: ATR period (default 14)
            
        Returns:
            ATR values
        """
        prev_close = close.shift(1)
        
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    @staticmethod
    def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        """
        Volume Weighted Average Price.
        
        Args:
            high: High prices
            low: Low prices
            close: Close prices
            volume: Volume data
            
        Returns:
            VWAP values
        """
        typical_price = (high + low + close) / 3
        volume_price = typical_price * volume
        
        cumulative_volume_price = volume_price.cumsum()
        cumulative_volume = volume.cumsum()
        
        vwap = cumulative_volume_price / cumulative_volume
        
        return vwap
    
    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Average Directional Index (trend strength).
        
        Returns:
            ADX values (0-100, higher = stronger trend)
        """
        # Calculate +DM and -DM
        high_diff = high.diff()
        low_diff = low.diff()
        
        plus_dm = high_diff.where((high_diff > low_diff.abs()) & (high_diff > 0), 0)
        minus_dm = low_diff.abs().where((low_diff.abs() > high_diff) & (low_diff < 0), 0)
        
        # Calculate ATR for True Range
        atr_values = TechnicalIndicators.atr(high, low, close, period)
        
        # Calculate +DI and -DI
        plus_di = (plus_dm.rolling(window=period).mean() / atr_values) * 100
        minus_di = (minus_dm.rolling(window=period).mean() / atr_values) * 100
        
        # Calculate ADX
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
        adx = dx.rolling(window=period).mean()
        
        return adx
    
    @staticmethod
    def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """
        Stochastic Oscillator.
        
        Returns:
            Tuple of (%K, %D)
        """
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        
        k_percent = ((close - lowest_low) / (highest_high - lowest_low)) * 100
        d_percent = k_percent.rolling(window=d_period).mean()
        
        return k_percent, d_percent
    
    @staticmethod
    def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Williams %R momentum oscillator."""
        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()
        
        williams_r = ((highest_high - close) / (highest_high - lowest_low)) * -100
        
        return williams_r
    
    @staticmethod
    def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
        """Commodity Channel Index."""
        typical_price = (high + low + close) / 3
        sma_tp = typical_price.rolling(window=period).mean()
        mean_deviation = typical_price.rolling(window=period).apply(lambda x: np.mean(np.abs(x - x.mean())))
        
        cci = (typical_price - sma_tp) / (0.015 * mean_deviation)
        
        return cci
    
    @staticmethod
    def fibonacci_retracements(high_price: float, low_price: float) -> dict:
        """
        Calculate Fibonacci retracement levels.
        
        Args:
            high_price: Recent swing high
            low_price: Recent swing low
            
        Returns:
            Dictionary with retracement levels
        """
        diff = high_price - low_price
        
        levels = {
            '0%': high_price,
            '23.6%': high_price - 0.236 * diff,
            '38.2%': high_price - 0.382 * diff,
            '50%': high_price - 0.5 * diff,
            '61.8%': high_price - 0.618 * diff,
            '100%': low_price
        }
        
        return levels
    
    @staticmethod
    def pivot_points(high: float, low: float, close: float) -> dict:
        """
        Calculate pivot points and support/resistance levels.
        
        Args:
            high: Previous period high
            low: Previous period low
            close: Previous period close
            
        Returns:
            Dictionary with pivot levels
        """
        pivot = (high + low + close) / 3
        
        levels = {
            'PP': pivot,
            'R1': (2 * pivot) - low,
            'R2': pivot + (high - low),
            'R3': high + 2 * (pivot - low),
            'S1': (2 * pivot) - high,
            'S2': pivot - (high - low),
            'S3': low - 2 * (high - pivot)
        }
        
        return levels
    
    @staticmethod
    def bollinger_squeeze(high: pd.Series, low: pd.Series, close: pd.Series, 
                         bb_period: int = 20, kc_period: int = 20, kc_multiplier: float = 1.5) -> pd.Series:
        """
        Bollinger Band Squeeze indicator.
        
        Returns:
            Boolean series (True = squeeze, False = no squeeze)
        """
        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = TechnicalIndicators.bollinger_bands(close, bb_period)
        
        # Keltner Channels
        atr_values = TechnicalIndicators.atr(high, low, close, kc_period)
        kc_middle = close.rolling(window=kc_period).mean()
        kc_upper = kc_middle + (kc_multiplier * atr_values)
        kc_lower = kc_middle - (kc_multiplier * atr_values)
        
        # Squeeze occurs when BB is inside KC
        squeeze = (bb_upper <= kc_upper) & (bb_lower >= kc_lower)
        
        return squeeze
    
    @staticmethod
    def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, 
                  period: int = 7, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
        """
        SuperTrend indicator.
        
        Returns:
            Tuple of (supertrend_values, trend_direction)
            trend_direction: 1 = uptrend, -1 = downtrend
        """
        atr_values = TechnicalIndicators.atr(high, low, close, period)
        hl2 = (high + low) / 2
        
        # Calculate basic upper and lower bands
        upper_band = hl2 + (multiplier * atr_values)
        lower_band = hl2 - (multiplier * atr_values)
        
        # Initialize arrays
        supertrend = pd.Series(index=close.index, dtype=float)
        trend = pd.Series(index=close.index, dtype=int)
        
        # Calculate SuperTrend
        for i in range(len(close)):
            if i == 0:
                supertrend.iloc[i] = lower_band.iloc[i]
                trend.iloc[i] = 1
            else:
                if close.iloc[i] <= supertrend.iloc[i-1]:
                    supertrend.iloc[i] = upper_band.iloc[i]
                    trend.iloc[i] = -1
                else:
                    supertrend.iloc[i] = lower_band.iloc[i]
                    trend.iloc[i] = 1
        
        return supertrend, trend
    
    @staticmethod
    def ichimoku_cloud(high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
        """
        Ichimoku Cloud indicator.
        
        Returns:
            Dictionary with all Ichimoku components
        """
        # Tenkan-sen (Conversion Line): 9-period
        tenkan_sen = (high.rolling(window=9).max() + low.rolling(window=9).min()) / 2
        
        # Kijun-sen (Base Line): 26-period  
        kijun_sen = (high.rolling(window=26).max() + low.rolling(window=26).min()) / 2
        
        # Senkou Span A (Leading Span A): (Tenkan + Kijun) / 2, plotted 26 periods ahead
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(26)
        
        # Senkou Span B (Leading Span B): 52-period midpoint, plotted 26 periods ahead
        senkou_span_b = ((high.rolling(window=52).max() + low.rolling(window=52).min()) / 2).shift(26)
        
        # Chikou Span (Lagging Span): Current close plotted 26 periods back
        chikou_span = close.shift(-26)
        
        return {
            'tenkan_sen': tenkan_sen,
            'kijun_sen': kijun_sen,
            'senkou_span_a': senkou_span_a,
            'senkou_span_b': senkou_span_b,
            'chikou_span': chikou_span
        }
    
    @staticmethod
    def heikin_ashi(open_price: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
        """
        Heikin Ashi candles for trend analysis.
        
        Returns:
            Dictionary with HA OHLC values
        """
        ha_close = (open_price + high + low + close) / 4
        ha_open = pd.Series(index=open_price.index, dtype=float)
        ha_open.iloc[0] = (open_price.iloc[0] + close.iloc[0]) / 2
        
        for i in range(1, len(open_price)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        
        ha_high = pd.concat([high, ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([low, ha_open, ha_close], axis=1).min(axis=1)
        
        return {
            'ha_open': ha_open,
            'ha_high': ha_high,
            'ha_low': ha_low,
            'ha_close': ha_close
        }
    
    @staticmethod 
    def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all major indicators for a OHLCV DataFrame.
        
        Args:
            df: DataFrame with columns: open, high, low, close, volume
            
        Returns:
            DataFrame with all indicators added
        """
        result_df = df.copy()
        
        try:
            # Moving averages
            result_df['sma_20'] = TechnicalIndicators.sma(df['close'], 20)
            result_df['sma_50'] = TechnicalIndicators.sma(df['close'], 50)
            result_df['ema_12'] = TechnicalIndicators.ema(df['close'], 12)
            result_df['ema_26'] = TechnicalIndicators.ema(df['close'], 26)
            
            # Bollinger Bands
            bb_upper, bb_middle, bb_lower = TechnicalIndicators.bollinger_bands(df['close'])
            result_df['bb_upper'] = bb_upper
            result_df['bb_middle'] = bb_middle
            result_df['bb_lower'] = bb_lower
            result_df['bb_width'] = (bb_upper - bb_lower) / bb_middle
            
            # RSI
            result_df['rsi'] = TechnicalIndicators.rsi(df['close'])
            
            # MACD
            macd_line, signal_line, histogram = TechnicalIndicators.macd(df['close'])
            result_df['macd'] = macd_line
            result_df['macd_signal'] = signal_line
            result_df['macd_histogram'] = histogram
            
            # ATR
            result_df['atr'] = TechnicalIndicators.atr(df['high'], df['low'], df['close'])
            
            # VWAP
            result_df['vwap'] = TechnicalIndicators.vwap(df['high'], df['low'], df['close'], df['volume'])
            
            # ADX (trend strength)
            result_df['adx'] = TechnicalIndicators.adx(df['high'], df['low'], df['close'])
            
            # Stochastic
            k_percent, d_percent = TechnicalIndicators.stochastic(df['high'], df['low'], df['close'])
            result_df['stoch_k'] = k_percent
            result_df['stoch_d'] = d_percent
            
            # Williams %R
            result_df['williams_r'] = TechnicalIndicators.williams_r(df['high'], df['low'], df['close'])
            
            # Bollinger Squeeze
            result_df['bb_squeeze'] = TechnicalIndicators.bollinger_squeeze(df['high'], df['low'], df['close'])
            
            # SuperTrend
            supertrend_values, trend_direction = TechnicalIndicators.supertrend(df['high'], df['low'], df['close'])
            result_df['supertrend'] = supertrend_values
            result_df['supertrend_direction'] = trend_direction
            
            logger.info(f"Calculated all indicators for {len(result_df)} candles")
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            
        return result_df