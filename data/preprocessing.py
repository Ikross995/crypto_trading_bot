"""
Feature engineering and preprocessing for machine learning models.

Handles data normalization, feature creation, and preparation for LSTM/GPT models.
"""

import logging

import numpy as np
import pandas as pd

# Import safe sklearn utilities
from core.utils import sklearn_components

# Extract sklearn classes from safe import
StandardScaler = sklearn_components['StandardScaler']
MinMaxScaler = sklearn_components['MinMaxScaler']
RobustScaler = sklearn_components['RobustScaler']
SelectKBest = sklearn_components['SelectKBest']
f_regression = sklearn_components['f_regression']

import warnings  # noqa: E402

warnings.filterwarnings('ignore')

from .indicators import TechnicalIndicators  # noqa: E402

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Feature engineering for trading data.

    Creates features for machine learning models including:
    - Technical indicators
    - Price patterns
    - Volume features
    - Time-based features
    - Market microstructure features
    """

    def __init__(self,
                 lookback_periods: list[int] = None,
                 price_features: bool = True,
                 volume_features: bool = True,
                 time_features: bool = True,
                 pattern_features: bool = True):

        if lookback_periods is None:
            lookback_periods = [5, 10, 20, 50]
        self.lookback_periods = lookback_periods
        self.price_features = price_features
        self.volume_features = volume_features
        self.time_features = time_features
        self.pattern_features = pattern_features

        # Fitted scalers for inference
        self.feature_scaler = None
        self.target_scaler = None
        self.feature_selector = None

        # Feature names for tracking
        self.feature_names = []

    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create comprehensive feature set from OHLCV data.

        Args:
            df: DataFrame with OHLCV data and indicators

        Returns:
            DataFrame with engineered features
        """
        logger.info(f"Creating features for {len(df)} samples")

        features_df = df.copy()

        # Add technical indicators if not present
        if 'rsi' not in features_df.columns:
            features_df = TechnicalIndicators.calculate_all_indicators(features_df)

        # Price-based features
        if self.price_features:
            features_df = self._add_price_features(features_df)

        # Volume-based features
        if self.volume_features:
            features_df = self._add_volume_features(features_df)

        # Time-based features
        if self.time_features:
            features_df = self._add_time_features(features_df)

        # Pattern features
        if self.pattern_features:
            features_df = self._add_pattern_features(features_df)

        # Lag features for different lookback periods
        features_df = self._add_lag_features(features_df)

        # Statistical features
        features_df = self._add_statistical_features(features_df)

        # Market microstructure features
        features_df = self._add_microstructure_features(features_df)

        # Clean up and remove invalid values
        features_df = self._clean_features(features_df)

        logger.info(f"Created {features_df.shape[1]} features")
        return features_df

    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add price-based features."""

        # Returns
        df['returns_1'] = df['close'].pct_change(1)
        df['returns_5'] = df['close'].pct_change(5)
        df['returns_10'] = df['close'].pct_change(10)

        # Log returns
        df['log_returns_1'] = np.log(df['close']).diff(1)
        df['log_returns_5'] = np.log(df['close']).diff(5)

        # Price position within range
        df['price_position'] = (df['close'] - df['low']) / (df['high'] - df['low'])

        # Gap analysis
        df['gap'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)

        # High-Low spread
        df['hl_spread'] = (df['high'] - df['low']) / df['close']

        # Open-Close spread
        df['oc_spread'] = (df['close'] - df['open']) / df['open']

        # Volatility proxy
        df['volatility'] = df['returns_1'].rolling(window=20).std()

        # Price momentum
        for period in [5, 10, 20]:
            df[f'momentum_{period}'] = df['close'] / df['close'].shift(period) - 1

        return df

    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume-based features."""

        # Volume ratios
        df['volume_sma_ratio'] = df['volume'] / df['volume'].rolling(window=20).mean()

        # Volume-price relationship
        df['vp_ratio'] = df['volume'] * df['close']
        df['volume_change'] = df['volume'].pct_change(1)

        # On-Balance Volume (OBV)
        df['obv'] = (df['volume'] * np.where(df['close'] > df['close'].shift(1), 1,
                    np.where(df['close'] < df['close'].shift(1), -1, 0))).cumsum()

        # Volume oscillator
        df['volume_oscillator'] = (df['volume'].rolling(5).mean() -
                                  df['volume'].rolling(10).mean()) / df['volume'].rolling(10).mean()

        # Accumulation/Distribution Line
        df['ad_line'] = (((df['close'] - df['low']) - (df['high'] - df['close'])) /
                        (df['high'] - df['low']) * df['volume']).cumsum()

        return df

    def _add_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add time-based features."""

        if df.index.dtype == 'datetime64[ns]':
            df['hour'] = df.index.hour
            df['day_of_week'] = df.index.dayofweek
            df['month'] = df.index.month

            # Cyclical encoding for time features
            df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
            df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
            df['dow_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
            df['dow_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)

            # Market session features
            df['is_market_hours'] = ((df['hour'] >= 9) & (df['hour'] <= 16)).astype(int)
            df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)

        return df

    def _add_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add candlestick pattern features."""

        # Basic candlestick patterns
        body_size = abs(df['close'] - df['open'])
        upper_shadow = df['high'] - np.maximum(df['open'], df['close'])
        lower_shadow = np.minimum(df['open'], df['close']) - df['low']

        df['body_size'] = body_size / df['close']
        df['upper_shadow'] = upper_shadow / df['close']
        df['lower_shadow'] = lower_shadow / df['close']
        df['total_shadow'] = (upper_shadow + lower_shadow) / df['close']

        # Doji patterns
        df['is_doji'] = (body_size <= (df['high'] - df['low']) * 0.1).astype(int)

        # Hammer/Hanging man
        df['is_hammer'] = ((lower_shadow >= 2 * body_size) &
                          (upper_shadow <= 0.1 * body_size)).astype(int)

        # Engulfing patterns
        prev_body = abs(df['close'].shift(1) - df['open'].shift(1))
        df['is_bullish_engulfing'] = ((df['close'] > df['open']) &
                                     (df['close'].shift(1) < df['open'].shift(1)) &
                                     (body_size > prev_body)).astype(int)

        df['is_bearish_engulfing'] = ((df['close'] < df['open']) &
                                     (df['close'].shift(1) > df['open'].shift(1)) &
                                     (body_size > prev_body)).astype(int)

        return df

    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add lagged features for different lookback periods."""

        key_features = ['close', 'volume', 'rsi', 'macd', 'bb_upper', 'bb_lower', 'atr']

        for feature in key_features:
            if feature in df.columns:
                for lag in self.lookback_periods:
                    df[f'{feature}_lag_{lag}'] = df[feature].shift(lag)

        return df

    def _add_statistical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add statistical features over rolling windows."""

        # Rolling statistics for returns
        for window in [5, 10, 20]:
            df[f'returns_mean_{window}'] = df['returns_1'].rolling(window).mean()
            df[f'returns_std_{window}'] = df['returns_1'].rolling(window).std()
            df[f'returns_skew_{window}'] = df['returns_1'].rolling(window).skew()
            df[f'returns_kurt_{window}'] = df['returns_1'].rolling(window).kurt()

        # Price percentiles
        for window in [20, 50]:
            df[f'price_percentile_{window}'] = df['close'].rolling(window).rank(pct=True)
            df[f'volume_percentile_{window}'] = df['volume'].rolling(window).rank(pct=True)

        # Bollinger Band position
        if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
            df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        return df

    def _add_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add market microstructure features."""

        # Bid-ask spread proxy (using high-low)
        df['spread_proxy'] = (df['high'] - df['low']) / df['close']

        # Price impact proxy
        df['price_impact'] = abs(df['returns_1']) / np.log(1 + df['volume'])

        # Amihud illiquidity measure
        df['illiquidity'] = abs(df['returns_1']) / df['volume']

        # Volume-synchronized probability of informed trading (VPIN) proxy
        df['vpin_proxy'] = abs(df['volume'] * df['returns_1']).rolling(20).sum() / df['volume'].rolling(20).sum()

        return df

    def _clean_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean features by handling infinities and NaN values."""

        # Replace infinities with NaN
        df.replace([np.inf, -np.inf], np.nan, inplace=True)

        # Forward fill first, then backward fill
        df.fillna(method='ffill', inplace=True)
        df.fillna(method='bfill', inplace=True)

        # Drop any remaining NaN rows
        df.dropna(inplace=True)

        return df

    def prepare_ml_features(self, df: pd.DataFrame,
                           target_column: str = 'close',
                           prediction_horizon: int = 1,
                           train_split: float = 0.8) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare features for machine learning models.

        Args:
            df: DataFrame with features
            target_column: Column to predict
            prediction_horizon: How many periods ahead to predict
            train_split: Fraction of data for training

        Returns:
            Tuple of (X_train, X_test, y_train, y_test)
        """

        # Create target variable (future price change)
        if target_column == 'close':
            df['target'] = df['close'].shift(-prediction_horizon) / df['close'] - 1
        else:
            df['target'] = df[target_column].shift(-prediction_horizon)

        # Drop rows with NaN targets
        df.dropna(inplace=True)

        # Select feature columns (exclude OHLCV and target)
        exclude_cols = ['open', 'high', 'low', 'close', 'volume', 'target']
        feature_cols = [col for col in df.columns if col not in exclude_cols]

        X = df[feature_cols].values
        y = df['target'].values

        # Split data
        split_idx = int(len(X) * train_split)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        # Fit scalers on training data
        self.feature_scaler = StandardScaler()
        self.target_scaler = StandardScaler()

        X_train_scaled = self.feature_scaler.fit_transform(X_train)
        X_test_scaled = self.feature_scaler.transform(X_test)

        y_train_scaled = self.target_scaler.fit_transform(y_train.reshape(-1, 1)).ravel()
        y_test_scaled = self.target_scaler.transform(y_test.reshape(-1, 1)).ravel()

        # Feature selection
        self.feature_selector = SelectKBest(f_regression, k=min(50, X_train_scaled.shape[1]))
        X_train_selected = self.feature_selector.fit_transform(X_train_scaled, y_train_scaled)
        X_test_selected = self.feature_selector.transform(X_test_scaled)

        # Store feature names
        selected_indices = self.feature_selector.get_support(indices=True)
        self.feature_names = [feature_cols[i] for i in selected_indices]

        logger.info(f"Prepared ML features: {X_train_selected.shape[1]} features, {len(X_train_selected)} training samples")

        return X_train_selected, X_test_selected, y_train_scaled, y_test_scaled

    def create_sequences(self, X: np.ndarray, y: np.ndarray,
                        sequence_length: int = 60) -> tuple[np.ndarray, np.ndarray]:
        """
        Create sequences for LSTM models.

        Args:
            X: Feature matrix
            y: Target vector
            sequence_length: Length of sequences

        Returns:
            Tuple of (X_sequences, y_sequences)
        """

        X_sequences = []
        y_sequences = []

        for i in range(sequence_length, len(X)):
            X_sequences.append(X[i-sequence_length:i])
            y_sequences.append(y[i])

        X_sequences = np.array(X_sequences)
        y_sequences = np.array(y_sequences)

        logger.info(f"Created sequences: {X_sequences.shape}")

        return X_sequences, y_sequences

    def inverse_transform_predictions(self, predictions: np.ndarray) -> np.ndarray:
        """
        Inverse transform scaled predictions back to original scale.

        Args:
            predictions: Scaled predictions

        Returns:
            Predictions in original scale
        """
        if self.target_scaler is not None:
            return self.target_scaler.inverse_transform(predictions.reshape(-1, 1)).ravel()
        return predictions

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Get feature importance from feature selector.

        Returns:
            DataFrame with feature names and importance scores
        """
        if self.feature_selector is None or not self.feature_names:
            return pd.DataFrame()

        scores = self.feature_selector.scores_
        selected_indices = self.feature_selector.get_support(indices=True)
        selected_scores = scores[selected_indices]

        importance_df = pd.DataFrame({
            'feature': self.feature_names,
            'importance': selected_scores
        }).sort_values('importance', ascending=False)

        return importance_df

    def generate_summary(self, df: pd.DataFrame) -> dict:
        """
        Generate feature engineering summary.

        Args:
            df: DataFrame with features

        Returns:
            Summary dictionary
        """

        numeric_cols = df.select_dtypes(include=[np.number]).columns

        summary = {
            'total_features': len(df.columns),
            'numeric_features': len(numeric_cols),
            'total_samples': len(df),
            'missing_values': df.isnull().sum().sum(),
            'feature_categories': {
                'price_features': len([c for c in df.columns if any(p in c for p in ['returns', 'momentum', 'volatility'])]),
                'volume_features': len([c for c in df.columns if 'volume' in c or c in ['obv', 'ad_line']]),
                'technical_indicators': len([c for c in df.columns if any(i in c for i in ['rsi', 'macd', 'bb', 'atr', 'adx'])]),
                'lag_features': len([c for c in df.columns if 'lag' in c]),
                'statistical_features': len([c for c in df.columns if any(s in c for s in ['mean', 'std', 'skew', 'kurt', 'percentile'])]),
                'pattern_features': len([c for c in df.columns if any(p in c for p in ['body_size', 'shadow', 'doji', 'hammer', 'engulfing'])])
            }
        }

        return summary
