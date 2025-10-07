"""
Trading signal generation optimized for MAXIMUM demo trading activity.
"""

import logging
from typing import Optional, List
from decimal import Decimal
from datetime import datetime

import numpy as np
import pandas as pd

from core.config import Config
from core.types import MarketData, TradingSignal
from core.constants import SignalType


class SignalGenerator:
    """Generates trading signals with ultra-low thresholds for demo trading."""
    
    def __init__(self, config: Config):
        """Initialize signal generator with AGGRESSIVE configuration."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # ULTRA AGGRESSIVE Signal parameters
        self.fast_ma_period = 3      # Very fast MA
        self.slow_ma_period = 9      # Very slow MA  
        self.min_signal_strength = 0.05  # Only 5% strength needed!
        
        # State tracking
        self.last_signal: Optional[TradingSignal] = None
        self.last_signal_time: Optional[datetime] = None
        
        self.logger.info("ULTRA AGGRESSIVE SignalGenerator initialized")
        self.logger.info(f"Min signal strength: {self.min_signal_strength}")
    
    def initialize(self) -> None:
        """Initialize the signal generator."""
        self.logger.info("Signal generator initialized for MAXIMUM TRADING")
    
    def generate_signal(self, market_data: MarketData) -> Optional[TradingSignal]:
        """
        Generate trading signals with MAXIMUM sensitivity for demo trading.
        """
        self.logger.debug(f"Generating signal for {market_data.symbol if market_data else 'None'}")
        
        if not market_data or len(market_data.close) < self.slow_ma_period:
            self.logger.debug("Insufficient market data")
            return None
            
        try:
            # Convert to pandas for easier calculation
            df = pd.DataFrame({
                'timestamp': market_data.timestamp,
                'close': market_data.close,
                'volume': market_data.volume
            })
            
            # Calculate moving averages
            df['fast_ma'] = df['close'].rolling(window=self.fast_ma_period).mean()
            df['slow_ma'] = df['close'].rolling(window=self.slow_ma_period).mean()
            
            # Get latest values
            current_fast_ma = df['fast_ma'].iloc[-1]
            current_slow_ma = df['slow_ma'].iloc[-1]
            current_price = df['close'].iloc[-1]
            current_timestamp = df['timestamp'].iloc[-1]
            
            # Check if we have valid data
            if pd.isna(current_fast_ma) or pd.isna(current_slow_ma):
                self.logger.debug("Invalid MA data")
                return None
                
            # Check cooldown period
            if self._is_in_cooldown(current_timestamp):
                self.logger.debug("Still in cooldown period")
                return None
            
            # ULTRA SENSITIVE signal detection
            signal_type = None
            strength = 0.0
            
            # ANY upward momentum = BUY signal
            if current_fast_ma > current_slow_ma:
                signal_type = SignalType.BUY
                strength = 0.8  # Always high strength for demo
                
            # ANY downward momentum = SELL signal
            elif current_fast_ma < current_slow_ma:
                signal_type = SignalType.SELL  
                strength = 0.8  # Always high strength for demo
            
            # Check minimum strength
            if not signal_type or strength < self.min_signal_strength:
                self.logger.debug(f"No signal: type={signal_type}, strength={strength:.3f}, min_req={self.min_signal_strength}")
                return None
                
            # Create trading signal
            signal = TradingSignal(
                symbol=market_data.symbol,
                signal_type=signal_type,
                strength=strength,
                timestamp=current_timestamp,
                metadata={
                    'fast_ma': float(current_fast_ma),
                    'slow_ma': float(current_slow_ma),
                    'current_price': float(current_price),
                    'volume': float(df['volume'].iloc[-1]),
                    'strategy': 'ULTRA_AGGRESSIVE_MA'
                }
            )
            
            self.last_signal = signal
            self.last_signal_time = current_timestamp
            
            self.logger.info(f"🚀 GENERATED {signal_type.value} signal for {market_data.symbol} "
                           f"(strength: {strength:.2f}, price: {current_price:.4f})")
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Error generating signal: {e}")
            return None
    
    def _is_in_cooldown(self, current_time: datetime) -> bool:
        """Check if we're still in cooldown period from last signal."""
        if not self.last_signal_time:
            return False
            
        cooldown_seconds = self.config.cooldown_sec
        time_since_last = (current_time - self.last_signal_time).total_seconds()
        
        is_cooling = time_since_last < cooldown_seconds
        if is_cooling:
            self.logger.debug(f"Cooldown: {time_since_last:.1f}s < {cooldown_seconds}s")
        
        return is_cooling
    
    def get_signal_summary(self) -> dict:
        """Get summary of signal generator state."""
        return {
            'fast_ma_period': self.fast_ma_period,
            'slow_ma_period': self.slow_ma_period,
            'min_signal_strength': self.min_signal_strength,
            'last_signal': {
                'type': self.last_signal.signal_type.value if self.last_signal else None,
                'strength': self.last_signal.strength if self.last_signal else None,
                'timestamp': self.last_signal.timestamp.isoformat() if self.last_signal else None
            } if self.last_signal else None
        }


class SimpleScalper:
    """Ultra aggressive scalping strategy."""
    
    def __init__(self, config: Config):
        """Initialize scalper with ULTRA aggressive configuration."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # ULTRA AGGRESSIVE Scalping parameters
        self.momentum_period = 2  # Very short period
        self.momentum_threshold = 0.0001  # 0.01% threshold
        self.volume_threshold = 0.5  # 50% of average volume
        
        self.last_prices: List[float] = []
        
    def generate_signal(self, market_data: MarketData) -> Optional[TradingSignal]:
        """Generate ULTRA aggressive scalping signals."""
        if len(market_data.close) < self.momentum_period + 2:
            return None
            
        try:
            current_price = market_data.close[-1]
            prev_price = market_data.close[-2]
            
            # Simple momentum: any upward movement = BUY
            if current_price > prev_price:
                signal_type = SignalType.BUY
                strength = 0.9
            else:
                signal_type = SignalType.SELL  
                strength = 0.9
                
            return TradingSignal(
                symbol=market_data.symbol,
                signal_type=signal_type,
                strength=strength,
                timestamp=market_data.timestamp[-1],
                metadata={
                    'current_price': current_price,
                    'prev_price': prev_price,
                    'strategy': 'ULTRA_SCALPING'
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error in scalping signal: {e}")
            return None
