"""
Tests for configuration module.

Tests environment variable loading, validation, and defaults.
"""

import os
from unittest.mock import patch

import pytest

from core.config import Config, load_config, reload_config


class TestConfigValidation:
    """Test configuration validation."""

    def test_config_defaults(self):
        """Test default configuration values."""
        with patch.dict(os.environ, {}, clear=True):
            # Set minimum required env vars
            with patch.dict(
                os.environ,
                {"BINANCE_API_KEY": "test_key", "BINANCE_API_SECRET": "test_secret"},
            ):
                config = load_config()

                # Test defaults
                assert config.mode.value == "paper"
                assert config.testnet is True
                assert config.symbols == ["BTCUSDT", "ETHUSDT"]
                assert config.timeframe == "1m"
                assert config.leverage == 5
                assert config.risk_per_trade_pct == 0.5

    def test_config_from_env(self):
        """Test configuration loading from environment variables."""
        env_vars = {
            "MODE": "live",
            "TESTNET": "false",
            "BINANCE_API_KEY": "live_key",
            "BINANCE_API_SECRET": "live_secret",
            "SYMBOLS": "BTCUSDT,SOLUSDT,ADAUSDT",
            "TIMEFRAME": "5m",
            "LEVERAGE": "10",
            "RISK_PER_TRADE_PCT": "1.0",
            "MAX_DAILY_LOSS_PCT": "3.0",
            "TP_LEVELS": "0.5,1.0,2.0,3.0",
            "TP_SHARES": "0.3,0.3,0.2,0.2",
            "SL_FIXED_PCT": "1.5",
        }

        with patch.dict(os.environ, env_vars):
            config = load_config()

            assert config.mode.value == "live"
            assert config.testnet is False
            assert config.binance_api_key == "live_key"
            assert config.symbols == ["BTCUSDT", "SOLUSDT", "ADAUSDT"]
            assert config.timeframe == "5m"
            assert config.leverage == 10
            assert config.risk_per_trade_pct == 1.0
            assert config.max_daily_loss_pct == 3.0
            assert config.parse_tp_levels() == [0.5, 1.0, 2.0, 3.0]
            assert config.parse_tp_shares() == [0.3, 0.3, 0.2, 0.2]
            assert config.sl_fixed_pct == 1.5

    def test_config_missing_api_keys(self):
        """Test configuration fails without API keys."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
            with pytest.raises(ValueError, match="BINANCE_API_KEY is required"):
                config.validate_api_credentials()

    def test_config_invalid_mode(self):
        """Test configuration fails with invalid mode."""
        env_vars = {
            "MODE": "invalid",
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
        }

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValueError, match="MODE must be one of"):
                Config()

    def test_config_invalid_timeframe(self):
        """Test configuration fails with invalid timeframe."""
        env_vars = {
            "TIMEFRAME": "invalid",
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
        }

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValueError, match="TIMEFRAME must be one of"):
                Config()

    def test_config_tp_mismatch(self):
        """Test configuration fails when TP levels and shares don't match."""
        env_vars = {
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
            "TP_LEVELS": "0.5,1.0,2.0",
            "TP_SHARES": "0.5,0.5",  # Mismatch: 3 levels, 2 shares
        }

        with patch.dict(os.environ, env_vars):
            with pytest.raises(
                ValueError, match="TP_LEVELS and TP_SHARES must have same length"
            ):
                Config()

    def test_config_tp_shares_sum(self):
        """Test configuration validates TP shares sum to 1.0."""
        env_vars = {
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
            "TP_LEVELS": "0.5,1.0",
            "TP_SHARES": "0.4,0.4",  # Sum = 0.8, should be 1.0
        }

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValueError, match="TP_SHARES must sum to 1.0"):
                Config()

    def test_config_negative_risk(self):
        """Test configuration fails with negative risk percentage."""
        env_vars = {
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
            "RISK_PER_TRADE_PCT": "-1.0",
        }

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValueError, match="RISK_PER_TRADE_PCT must be positive"):
                Config()

    def test_config_excessive_leverage(self):
        """Test configuration fails with excessive leverage."""
        env_vars = {
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
            "LEVERAGE": "200",  # Too high
        }

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValueError, match="LEVERAGE must be between 1 and 125"):
                Config()

    def test_config_boolean_parsing(self):
        """Test boolean environment variable parsing."""
        # Test various boolean representations
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
        ]

        for str_val, expected in test_cases:
            env_vars = {
                "BINANCE_API_KEY": "test_key",
                "BINANCE_API_SECRET": "test_secret",
                "TESTNET": str_val,
            }

            with patch.dict(os.environ, env_vars):
                config = load_config()
                assert config.testnet == expected, f"Failed for input: {str_val}"

    def test_config_list_parsing(self):
        """Test list parsing from comma-separated strings."""
        env_vars = {
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
            "SYMBOLS": "  BTCUSDT  ,  ETHUSDT  ,  SOLUSDT  ",  # With spaces
        }

        with patch.dict(os.environ, env_vars):
            config = load_config()
            assert config.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_config_dca_ladder_parsing(self):
        """Test DCA ladder parsing."""
        env_vars = {
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
            "DCA_LADDER": "-0.5:1.0,-1.0:1.5,-2.0:2.0",
        }

        with patch.dict(os.environ, env_vars):
            config = load_config()
            expected = [(-0.5, 1.0), (-1.0, 1.5), (-2.0, 2.0)]
            assert config.dca_ladder == expected

    def test_config_optional_features(self):
        """Test optional feature flags."""
        env_vars = {
            "BINANCE_API_KEY": "test_key",
            "BINANCE_API_SECRET": "test_secret",
            "USE_LSTM": "true",
            "USE_GPT": "false",
            "USE_DCA": "true",
            "USE_WEBSOCKET": "false",
        }

        with patch.dict(os.environ, env_vars):
            config = load_config()
            assert config.use_lstm is True
            assert config.use_gpt is False
            assert config.use_dca is True
            assert config.use_websocket is False
