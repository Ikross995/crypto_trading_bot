"""
ML Data Manager for Large Klines Datasets

Manages training data preparation, memory optimization, and model training workflows
for large-scale cryptocurrency market data.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any, Union, Iterator
import logging
from datetime import datetime, timedelta
import pickle
import joblib
from dataclasses import dataclass, field
import gc
import psutil
import os

from .klines_processor import LargeKlinesProcessor, create_processor

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """Configuration for ML training data preparation."""
    sequence_length: int = 60
    prediction_horizon: int = 1
    features: Optional[List[str]] = None
    target_column: str = 'close'
    train_split: float = 0.8
    validation_split: float = 0.1
    test_split: float = 0.1
    normalize: bool = True
    remove_outliers: bool = True
    outlier_threshold: float = 3.0


class MLDataManager:
    """
    Manages ML training data from large klines datasets.
    
    Features:
    - Memory-efficient data loading and preprocessing
    - Train/validation/test splitting with time awareness
    - Feature engineering and normalization
    - Model training data preparation
    - Results caching and persistence
    """
    
    def __init__(self, 
                 processor: Optional[LargeKlinesProcessor] = None,
                 cache_dir: str = "data/ml_cache",
                 memory_limit_gb: float = 2.0):
        """
        Initialize ML data manager.
        
        Args:
            processor: Klines processor instance
            cache_dir: Directory for ML-specific cache
            memory_limit_gb: Memory limit in GB
        """
        self.processor = processor or create_processor()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.memory_limit_gb = memory_limit_gb
        self.memory_limit_mb = int(memory_limit_gb * 1024)
        
        # Training data storage
        self.datasets: Dict[str, Dict[str, np.ndarray]] = {}
        self.scalers: Dict[str, Any] = {}
        self.metadata: Dict[str, Dict] = {}
        
        # Memory monitoring
        self.process = psutil.Process(os.getpid())
    
    def prepare_training_data(self,
                             filepath: str,
                             config: TrainingConfig,
                             symbol: Optional[str] = None,
                             date_range: Optional[Tuple[str, str]] = None,
                             sample_ratio: float = 1.0) -> Dict[str, Dict[str, np.ndarray]]:
        """
        Prepare complete training dataset from large klines file.
        
        Args:
            filepath: Path to large CSV file
            config: Training configuration
            symbol: Optional symbol filter
            date_range: Optional date range filter
            sample_ratio: Fraction of data to use (1.0 = all data)
            
        Returns:
            Dictionary with train/val/test splits
        """
        logger.info(f"Preparing training data with config: {config}")
        
        # Monitor memory
        initial_memory = self._get_memory_usage_mb()
        
        # Load and preprocess data
        data = self._load_and_preprocess(
            filepath, config, symbol, date_range, sample_ratio
        )
        
        # Create features
        features = self._create_features(data, config)
        
        # Create target variable
        targets = self._create_targets(data, config)
        
        # Create sequences
        X, y = self._create_sequences_with_targets(
            features, targets, config.sequence_length, config.prediction_horizon
        )
        
        # Split data
        splits = self._create_time_splits(X, y, config)
        
        # Normalize if requested
        if config.normalize:
            splits = self._normalize_splits(splits, config)
        
        # Memory cleanup
        del data, features, targets, X, y
        gc.collect()
        
        final_memory = self._get_memory_usage_mb()
        logger.info(f"Training data prepared. Memory usage: {initial_memory:.1f} -> {final_memory:.1f} MB")
        
        # Cache dataset
        dataset_key = self._generate_dataset_key(filepath, config, symbol, date_range)
        self.datasets[dataset_key] = splits
        self.metadata[dataset_key] = {
            'config': config,
            'symbol': symbol,
            'date_range': date_range,
            'sample_ratio': sample_ratio,
            'created_at': datetime.now().isoformat(),
            'memory_mb': final_memory - initial_memory
        }
        
        return splits
    
    def _load_and_preprocess(self,
                            filepath: str,
                            config: TrainingConfig,
                            symbol: Optional[str],
                            date_range: Optional[Tuple[str, str]],
                            sample_ratio: float) -> pd.DataFrame:
        """Load and basic preprocessing of data."""
        
        if sample_ratio < 1.0:
            # Create sample first
            sample_file = self.cache_dir / f"sample_{symbol or 'all'}_{sample_ratio:.3f}.csv"
            
            if not sample_file.exists():
                logger.info(f"Creating {sample_ratio:.1%} sample")
                self.processor.create_training_sample(
                    filepath, str(sample_file), sample_ratio, symbol, 'random'
                )
            
            data = pd.read_csv(sample_file)
        else:
            # Load data in chunks
            logger.info("Loading full dataset in chunks")
            chunks = []
            
            for chunk in self.processor.load_chunk_iterator(
                filepath, chunk_size=50000, symbol_filter=symbol, date_filter=date_range
            ):
                chunks.append(chunk)
                
                # Memory check
                if self._get_memory_usage_mb() > self.memory_limit_mb * 0.8:
                    logger.warning("Approaching memory limit, processing current chunks")
                    break
            
            data = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        
        # Basic preprocessing
        if 'timestamp' in data.columns:
            data['timestamp'] = pd.to_datetime(data['timestamp'])
            data = data.sort_values('timestamp').reset_index(drop=True)
        
        # Remove outliers if requested
        if config.remove_outliers:
            data = self._remove_outliers(data, config.outlier_threshold)
        
        logger.info(f"Loaded and preprocessed {len(data):,} rows")
        return data
    
    def _create_features(self, data: pd.DataFrame, config: TrainingConfig) -> np.ndarray:
        """Create feature matrix from OHLCV data."""
        logger.info("Creating features from OHLCV data")
        
        # Use processor's feature preparation
        feature_config = {
            'price_features': True,
            'technical_indicators': True,
            'volume_features': True,
            'time_features': True,
            'sequence_length': 1  # We'll handle sequences separately
        }
        
        features_dict = self.processor.prepare_ml_features(data, feature_config)
        
        # Select requested features or use all
        if config.features:
            selected_features = []
            for feature_name in config.features:
                if feature_name in features_dict:
                    selected_features.append(features_dict[feature_name])
                else:
                    logger.warning(f"Feature '{feature_name}' not found")
            
            if selected_features:
                features = np.column_stack(selected_features)
            else:
                logger.warning("No valid features selected, using all")
                features = np.column_stack(list(features_dict.values()))
        else:
            # Use all features except sequences (we'll create our own)
            feature_arrays = []
            for key, value in features_dict.items():
                if not key.endswith('_seq') and len(value.shape) <= 2:
                    if len(value.shape) == 1:
                        feature_arrays.append(value.reshape(-1, 1))
                    else:
                        feature_arrays.append(value)
            
            features = np.column_stack(feature_arrays) if feature_arrays else np.array([])
        
        logger.info(f"Created features matrix: {features.shape}")
        return features
    
    def _create_targets(self, data: pd.DataFrame, config: TrainingConfig) -> np.ndarray:
        """Create target variable from price data."""
        if config.target_column not in data.columns:
            raise ValueError(f"Target column '{config.target_column}' not found")
        
        target_data = data[config.target_column].values
        
        # Create future returns as target
        if config.prediction_horizon == 1:
            # Next period return
            targets = np.log(target_data[1:] / target_data[:-1])
            targets = np.append(targets, 0)  # Pad last value
        else:
            # Multi-period return
            future_prices = np.roll(target_data, -config.prediction_horizon)
            targets = np.log(future_prices / target_data)
            targets[-config.prediction_horizon:] = 0  # Pad last values
        
        # Convert to binary classification (up/down)
        targets = (targets > 0).astype(int)
        
        logger.info(f"Created targets: {targets.shape}, positive ratio: {targets.mean():.3f}")
        return targets
    
    def _create_sequences_with_targets(self,
                                      features: np.ndarray,
                                      targets: np.ndarray,
                                      sequence_length: int,
                                      prediction_horizon: int) -> Tuple[np.ndarray, np.ndarray]:
        """Create sequences for LSTM training."""
        if len(features) != len(targets):
            min_len = min(len(features), len(targets))
            features = features[:min_len]
            targets = targets[:min_len]
        
        X, y = [], []
        
        for i in range(sequence_length, len(features) - prediction_horizon):
            X.append(features[i-sequence_length:i])
            y.append(targets[i + prediction_horizon - 1])
        
        X = np.array(X)
        y = np.array(y)
        
        logger.info(f"Created sequences: X={X.shape}, y={y.shape}")
        return X, y
    
    def _create_time_splits(self,
                           X: np.ndarray,
                           y: np.ndarray,
                           config: TrainingConfig) -> Dict[str, Dict[str, np.ndarray]]:
        """Create time-aware train/validation/test splits."""
        n_samples = len(X)
        
        train_end = int(n_samples * config.train_split)
        val_end = int(n_samples * (config.train_split + config.validation_split))
        
        splits = {
            'train': {
                'X': X[:train_end],
                'y': y[:train_end]
            },
            'validation': {
                'X': X[train_end:val_end],
                'y': y[train_end:val_end]
            },
            'test': {
                'X': X[val_end:],
                'y': y[val_end:]
            }
        }
        
        # Log split sizes
        for split_name, split_data in splits.items():
            logger.info(f"{split_name}: {len(split_data['X']):,} samples")
        
        return splits
    
    def _normalize_splits(self,
                         splits: Dict[str, Dict[str, np.ndarray]],
                         config: TrainingConfig) -> Dict[str, Dict[str, np.ndarray]]:
        """Normalize features using training set statistics."""
        try:
            from sklearn.preprocessing import StandardScaler
            
            # Fit scaler on training data
            train_X = splits['train']['X']
            
            # Reshape for scaling (samples * timesteps, features)
            train_X_flat = train_X.reshape(-1, train_X.shape[-1])
            
            scaler = StandardScaler()
            scaler.fit(train_X_flat)
            
            # Transform all splits
            for split_name in splits.keys():
                X = splits[split_name]['X']
                X_flat = X.reshape(-1, X.shape[-1])
                X_scaled = scaler.transform(X_flat)
                splits[split_name]['X'] = X_scaled.reshape(X.shape)
            
            # Store scaler for later use
            scaler_key = f"scaler_{len(self.scalers)}"
            self.scalers[scaler_key] = scaler
            
            logger.info(f"Normalized features using {scaler_key}")
            
        except ImportError:
            logger.warning("sklearn not available, skipping normalization")
        
        return splits
    
    def _remove_outliers(self, data: pd.DataFrame, threshold: float = 3.0) -> pd.DataFrame:
        """Remove outliers using z-score method."""
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        
        for col in numeric_cols:
            if col in ['open', 'high', 'low', 'close', 'volume']:
                z_scores = np.abs((data[col] - data[col].mean()) / data[col].std())
                data = data[z_scores < threshold]
        
        logger.info(f"Removed outliers, {len(data):,} rows remaining")
        return data.reset_index(drop=True)
    
    def _generate_dataset_key(self,
                             filepath: str,
                             config: TrainingConfig,
                             symbol: Optional[str],
                             date_range: Optional[Tuple[str, str]]) -> str:
        """Generate unique key for dataset caching."""
        components = [
            Path(filepath).stem,
            str(config.sequence_length),
            str(config.prediction_horizon),
            symbol or 'all',
            f"{date_range[0]}_{date_range[1]}" if date_range else 'all_dates'
        ]
        return "_".join(components)
    
    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        return self.process.memory_info().rss / (1024 * 1024)
    
    def save_dataset(self, dataset_key: str, filepath: str):
        """Save prepared dataset to disk."""
        if dataset_key not in self.datasets:
            raise ValueError(f"Dataset '{dataset_key}' not found")
        
        save_path = Path(filepath)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save using joblib for efficient numpy array storage
        save_data = {
            'splits': self.datasets[dataset_key],
            'metadata': self.metadata[dataset_key],
            'scalers': {k: v for k, v in self.scalers.items() if dataset_key in k}
        }
        
        joblib.dump(save_data, save_path)
        logger.info(f"Dataset saved to {save_path}")
    
    def load_dataset(self, filepath: str) -> str:
        """Load prepared dataset from disk."""
        save_path = Path(filepath)
        if not save_path.exists():
            raise FileNotFoundError(f"Dataset file not found: {save_path}")
        
        save_data = joblib.load(save_path)
        
        # Generate dataset key
        metadata = save_data['metadata']
        dataset_key = f"loaded_{save_path.stem}"
        
        self.datasets[dataset_key] = save_data['splits']
        self.metadata[dataset_key] = metadata
        self.scalers.update(save_data.get('scalers', {}))
        
        logger.info(f"Dataset loaded from {save_path}")
        return dataset_key
    
    def get_training_batch(self,
                          dataset_key: str,
                          split: str = 'train',
                          batch_size: int = 32,
                          shuffle: bool = True) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """Get training batches from prepared dataset."""
        if dataset_key not in self.datasets:
            raise ValueError(f"Dataset '{dataset_key}' not found")
        
        if split not in self.datasets[dataset_key]:
            raise ValueError(f"Split '{split}' not found in dataset")
        
        X = self.datasets[dataset_key][split]['X']
        y = self.datasets[dataset_key][split]['y']
        
        n_samples = len(X)
        indices = np.arange(n_samples)
        
        if shuffle:
            np.random.shuffle(indices)
        
        for i in range(0, n_samples, batch_size):
            batch_indices = indices[i:i + batch_size]
            yield X[batch_indices], y[batch_indices]
    
    def get_dataset_info(self, dataset_key: Optional[str] = None) -> Dict:
        """Get information about datasets."""
        if dataset_key:
            if dataset_key not in self.datasets:
                raise ValueError(f"Dataset '{dataset_key}' not found")
            
            info = self.metadata[dataset_key].copy()
            info['splits'] = {}
            
            for split_name, split_data in self.datasets[dataset_key].items():
                info['splits'][split_name] = {
                    'X_shape': split_data['X'].shape,
                    'y_shape': split_data['y'].shape,
                    'y_mean': split_data['y'].mean()
                }
            
            return info
        
        else:
            # Return info for all datasets
            return {
                'datasets': list(self.datasets.keys()),
                'memory_usage_mb': self._get_memory_usage_mb(),
                'cache_dir': str(self.cache_dir)
            }
    
    def clear_memory(self):
        """Clear all datasets from memory."""
        self.datasets.clear()
        self.scalers.clear()
        self.metadata.clear()
        gc.collect()
        logger.info("Memory cleared")


def create_ml_manager(processor: Optional[LargeKlinesProcessor] = None,
                     cache_dir: str = "data/ml_cache",
                     memory_limit_gb: float = 2.0) -> MLDataManager:
    """Convenience function to create ML data manager."""
    return MLDataManager(processor, cache_dir, memory_limit_gb)