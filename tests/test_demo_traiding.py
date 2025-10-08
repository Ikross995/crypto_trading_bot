"""
Tests for demo trading functionality.
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from core.config import load_config
from data.simulator import MarketSimulator
from exchange.client import BinanceMarketDataClient, MockBinanceClient
from exchange.positions import PositionManager
from strategy.signals import SignalGenerator
from core.constants import PositionSide, SignalType


class TestDemoTrading(unittest.TestCase):
    """Test demo trading functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = load_config()
        
    def test_market_simulator(self):
        """Test market simulator functionality."""
        simulator = MarketSimulator(self.config)
        simulator.initialize()
        
        # Test price generation
        btc_price = simulator.get_current_price('BTCUSDT')
        self.assertIsInstance(btc_price, Decimal)
        self.assertGreater(btc_price, 0)
        
        # Test klines generation
        market_data = simulator.get_klines('BTCUSDT', '1m', 10)
        self.assertIsNotNone(market_data)
        self.assertEqual(len(market_data.close), 10)
        self.assertEqual(market_data.symbol, 'BTCUSDT')
        
    def test_position_manager(self):
        """Test position manager functionality."""
        position_manager = PositionManager(self.config)
        position_manager.initialize()
        
        # Test initial state
        self.assertFalse(position_manager.has_position('BTCUSDT'))
        
        # Test position creation
        position = position_manager.update_position(
            symbol='BTCUSDT',
            side=PositionSide.LONG,
            size=Decimal('0.001'),
            price=Decimal('97000')
        )
        
        self.assertTrue(position_manager.has_position('BTCUSDT'))
        self.assertEqual(position.symbol, 'BTCUSDT')
        self.assertEqual(position.side, PositionSide.LONG)
        
    def test_signal_generator(self):
        """Test signal generator functionality."""
        import asyncio

        signal_generator = SignalGenerator(self.config)
        asyncio.run(signal_generator.initialize())
        
        # Generate market data
        simulator = MarketSimulator(self.config)
        simulator.initialize()
        market_data = simulator.get_klines('BTCUSDT', '1m', 50)
        
        self.assertIsNotNone(market_data)
        
        # Generate signal (may or may not produce a signal depending on data)
        signal = signal_generator.generate_signal(market_data)
        
        # Signal is optional, but if generated should be valid
        if signal:
            self.assertIn(signal.signal_type, [SignalType.BUY, SignalType.SELL])
            self.assertGreaterEqual(signal.strength, 0.0)
            self.assertLessEqual(signal.strength, 1.0)
            
    def test_mock_client(self):
        """Test mock Binance client."""
        mock_client = MockBinanceClient(10000.0)
        
        # Test initial balance
        balance = mock_client.get_balance()
        self.assertEqual(balance, Decimal('10000.0'))
        
        # Test mock order placement
        from core.constants import OrderSide, OrderType
        order_result = mock_client.place_order(
            symbol='BTCUSDT',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal('0.001')
        )
        
        self.assertIn('orderId', order_result)
        self.assertEqual(order_result['status'], 'FILLED')
        
    def test_market_data_client_fallback(self):
        """Test market data client fallback to simulator."""
        client = BinanceMarketDataClient(self.config)
        client.initialize()
        
        # Should use simulator due to API restrictions
        self.assertTrue(client._use_simulator)
        self.assertIsNotNone(client.simulator)
        
        # Test price fetching
        price = client.get_current_price('BTCUSDT')
        self.assertIsInstance(price, Decimal)
        self.assertGreater(price, 0)
        
        # Test market data fetching
        market_data = client.get_klines('BTCUSDT', '1m', 10)
        self.assertIsNotNone(market_data)
        self.assertEqual(len(market_data.close), 10)


if __name__ == '__main__':
    unittest.main()