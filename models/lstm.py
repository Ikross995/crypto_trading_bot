"""
LSTM Neural Network for price prediction.

Implements LSTM model with proper training, validation, and prediction capabilities.
"""

import numpy as np
import pandas as pd
import logging
from typing import Tuple, Optional, Dict, Any, List, Union
from pathlib import Path
import pickle
import json

try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers, optimizers, callbacks
    from tensorflow.keras.models import Sequential, load_model
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False

# Separate sklearn import
try:
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    # Fallback metrics functions
    def mean_absolute_error(y_true, y_pred):
        return float(sum(abs(a - b) for a, b in zip(y_true, y_pred)) / len(y_true))
    
    def mean_squared_error(y_true, y_pred):
        return float(sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / len(y_true))
    
from core.config import Config
from data.preprocessing import FeatureEngineer


logger = logging.getLogger(__name__)


class LSTMPredictor:
    """
    LSTM Neural Network for cryptocurrency price prediction.
    
    Features:
    - Multi-layer LSTM architecture
    - Dropout for regularization
    - Early stopping and model checkpointing
    - Prediction confidence estimation
    - Model persistence and loading
    """
    
    def __init__(self, 
                 sequence_length: int = 60,
                 lstm_units: List[int] = [100, 50, 25],
                 dropout_rate: float = 0.2,
                 learning_rate: float = 0.001,
                 batch_size: int = 32,
                 epochs: int = 100,
                 validation_split: float = 0.2):
        
        if not TENSORFLOW_AVAILABLE:
            raise ImportError("TensorFlow is required for LSTM model. Install with: pip install tensorflow")
        
        self.sequence_length = sequence_length
        self.lstm_units = lstm_units
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.epochs = epochs
        self.validation_split = validation_split
        
        # Model components
        self.model = None
        self.feature_engineer: Optional[FeatureEngineer] = None
        self.history: Optional[Dict] = None
        
        # Training metrics
        self.training_metrics = {}
        
    def build_model(self, input_shape: Tuple[int, int]):
        """
        Build LSTM model architecture.
        
        Args:
            input_shape: Shape of input sequences (sequence_length, n_features)
            
        Returns:
            Compiled Keras model
        """
        model = Sequential(name='LSTM_Predictor')
        
        # Input layer
        model.add(layers.InputLayer(input_shape=input_shape))
        
        # LSTM layers
        for i, units in enumerate(self.lstm_units):
            return_sequences = i < len(self.lstm_units) - 1  # Return sequences for all but last layer
            
            model.add(layers.LSTM(
                units=units,
                return_sequences=return_sequences,
                dropout=self.dropout_rate,
                recurrent_dropout=self.dropout_rate,
                name=f'lstm_{i+1}'
            ))
            
            # Additional dropout after each LSTM layer
            model.add(layers.Dropout(self.dropout_rate, name=f'dropout_{i+1}'))
        
        # Dense layers for final prediction
        model.add(layers.Dense(50, activation='relu', name='dense_1'))
        model.add(layers.Dropout(self.dropout_rate, name='final_dropout'))
        model.add(layers.Dense(1, activation='linear', name='output'))
        
        # Compile model
        optimizer = optimizers.Adam(learning_rate=self.learning_rate)
        model.compile(
            optimizer=optimizer,
            loss='mse',
            metrics=['mae', 'mse']
        )
        
        logger.info(f"Built LSTM model with architecture: {self.lstm_units}")
        model.summary(print_fn=logger.info)
        
        return model
    
    def prepare_data(self, df: pd.DataFrame, 
                    target_column: str = 'close',
                    prediction_horizon: int = 1) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare data for LSTM training.
        
        Args:
            df: DataFrame with OHLCV data
            target_column: Column to predict
            prediction_horizon: Steps ahead to predict
            
        Returns:
            Tuple of prepared data (X_train, X_test, y_train, y_test)
        """
        
        # Initialize feature engineer
        self.feature_engineer = FeatureEngineer()
        
        # Create features
        features_df = self.feature_engineer.create_features(df)
        
        # Prepare ML features
        X_train, X_test, y_train, y_test = self.feature_engineer.prepare_ml_features(
            features_df, target_column, prediction_horizon
        )
        
        # Create sequences for LSTM
        X_train_seq, y_train_seq = self.feature_engineer.create_sequences(
            X_train, y_train, self.sequence_length
        )
        X_test_seq, y_test_seq = self.feature_engineer.create_sequences(
            X_test, y_test, self.sequence_length
        )
        
        logger.info(f"Prepared LSTM data: {X_train_seq.shape}, {X_test_seq.shape}")
        
        return X_train_seq, X_test_seq, y_train_seq, y_test_seq
    
    def train(self, X_train: np.ndarray, y_train: np.ndarray,
             X_val: Optional[np.ndarray] = None, y_val: Optional[np.ndarray] = None,
             model_save_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Train LSTM model.
        
        Args:
            X_train: Training sequences
            y_train: Training targets
            X_val: Validation sequences (optional)
            y_val: Validation targets (optional)
            model_save_path: Path to save best model
            
        Returns:
            Training history and metrics
        """
        
        # Build model
        input_shape = (X_train.shape[1], X_train.shape[2])
        self.model = self.build_model(input_shape)
        
        # Callbacks
        callback_list = []
        
        # Early stopping
        early_stop = callbacks.EarlyStopping(
            monitor='val_loss' if X_val is not None else 'loss',
            patience=15,
            restore_best_weights=True,
            verbose=1
        )
        callback_list.append(early_stop)
        
        # Reduce learning rate on plateau
        reduce_lr = callbacks.ReduceLROnPlateau(
            monitor='val_loss' if X_val is not None else 'loss',
            factor=0.5,
            patience=10,
            min_lr=1e-7,
            verbose=1
        )
        callback_list.append(reduce_lr)
        
        # Model checkpoint
        if model_save_path:
            checkpoint = callbacks.ModelCheckpoint(
                model_save_path,
                monitor='val_loss' if X_val is not None else 'loss',
                save_best_only=True,
                save_weights_only=False,
                verbose=1
            )
            callback_list.append(checkpoint)
        
        # Prepare validation data
        validation_data = None
        if X_val is not None and y_val is not None:
            validation_data = (X_val, y_val)
        
        # Train model
        logger.info(f"Training LSTM model for {self.epochs} epochs...")
        
        history = self.model.fit(
            X_train, y_train,
            batch_size=self.batch_size,
            epochs=self.epochs,
            validation_data=validation_data,
            validation_split=self.validation_split if validation_data is None else 0,
            callbacks=callback_list,
            verbose=1,
            shuffle=True
        )
        
        self.history = history.history
        
        # Calculate training metrics
        train_predictions = self.model.predict(X_train)
        train_mae = mean_absolute_error(y_train, train_predictions)
        train_rmse = np.sqrt(mean_squared_error(y_train, train_predictions))
        
        self.training_metrics = {
            'train_mae': train_mae,
            'train_rmse': train_rmse,
            'final_train_loss': history.history['loss'][-1],
            'epochs_trained': len(history.history['loss'])
        }
        
        if validation_data is not None or self.validation_split > 0:
            if validation_data is not None:
                val_predictions = self.model.predict(X_val)
                val_mae = mean_absolute_error(y_val, val_predictions)
                val_rmse = np.sqrt(mean_squared_error(y_val, val_predictions))
            else:
                # Use validation split predictions (approximate)
                val_mae = min(history.history.get('val_mae', [float('inf')]))
                val_rmse = np.sqrt(min(history.history.get('val_loss', [float('inf')])))
            
            self.training_metrics.update({
                'val_mae': val_mae,
                'val_rmse': val_rmse,
                'final_val_loss': history.history['val_loss'][-1]
            })
        
        logger.info(f"Training completed. Final metrics: {self.training_metrics}")
        
        return {
            'history': self.history,
            'metrics': self.training_metrics,
            'model_summary': self._get_model_summary()
        }
    
    def predict(self, X: np.ndarray, return_confidence: bool = False) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
        """
        Make predictions with the trained model.
        
        Args:
            X: Input sequences for prediction
            return_confidence: Whether to return prediction confidence
            
        Returns:
            Predictions (and confidence if requested)
        """
        if self.model is None:
            raise ValueError("Model not trained or loaded")
        
        # Make predictions
        predictions = self.model.predict(X, batch_size=self.batch_size, verbose=0)
        predictions = predictions.flatten()
        
        # Transform back to original scale
        if self.feature_engineer and self.feature_engineer.target_scaler:
            predictions = self.feature_engineer.inverse_transform_predictions(predictions)
        
        if return_confidence:
            # Estimate confidence based on prediction variance
            # Use dropout during inference for Monte Carlo estimation
            mc_predictions = []
            n_samples = 100
            
            # Enable dropout during inference
            for layer in self.model.layers:
                if hasattr(layer, 'training'):
                    layer.training = True
            
            for _ in range(n_samples):
                mc_pred = self.model(X, training=True)
                mc_predictions.append(mc_pred.numpy().flatten())
            
            # Disable training mode
            for layer in self.model.layers:
                if hasattr(layer, 'training'):
                    layer.training = False
            
            mc_predictions = np.array(mc_predictions)
            confidence = np.std(mc_predictions, axis=0)
            
            return predictions, confidence
        
        return predictions
    
    def predict_next(self, recent_data: pd.DataFrame, n_steps: int = 1) -> Dict[str, Any]:
        """
        Predict next n steps based on recent data.
        
        Args:
            recent_data: Recent OHLCV data
            n_steps: Number of steps to predict ahead
            
        Returns:
            Dictionary with predictions and metadata
        """
        if self.model is None or self.feature_engineer is None:
            raise ValueError("Model not trained or loaded")
        
        # Prepare recent data
        features_df = self.feature_engineer.create_features(recent_data)
        
        # Get the last sequence_length samples
        if len(features_df) < self.sequence_length:
            raise ValueError(f"Need at least {self.sequence_length} samples for prediction")
        
        # Prepare features (excluding OHLCV and target)
        exclude_cols = ['open', 'high', 'low', 'close', 'volume']
        feature_cols = [col for col in features_df.columns if col not in exclude_cols]
        
        # Scale features
        recent_features = features_df[feature_cols].iloc[-self.sequence_length:].values
        if self.feature_engineer.feature_scaler:
            recent_features = self.feature_engineer.feature_scaler.transform(recent_features)
        
        # Feature selection
        if self.feature_engineer.feature_selector:
            recent_features = self.feature_engineer.feature_selector.transform(recent_features)
        
        # Reshape for LSTM
        X_recent = recent_features.reshape(1, self.sequence_length, -1)
        
        # Make predictions
        predictions, confidence = self.predict(X_recent, return_confidence=True)
        
        # Multi-step prediction (if requested)
        if n_steps > 1:
            # This is a simplified multi-step approach
            # In practice, you'd want to feed predictions back as inputs
            logger.warning("Multi-step prediction is simplified. Consider implementing recursive prediction.")
        
        return {
            'prediction': predictions[0],
            'confidence': confidence[0],
            'prediction_type': 'price_change_pct',
            'steps_ahead': n_steps,
            'timestamp': pd.Timestamp.now(),
            'model_version': self._get_model_version()
        }
    
    def save_model(self, filepath: str):
        """Save model and associated objects."""
        if self.model is None:
            raise ValueError("No model to save")
        
        model_path = Path(filepath)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save Keras model
        self.model.save(str(model_path))
        
        # Save feature engineer
        if self.feature_engineer:
            fe_path = model_path.parent / f"{model_path.stem}_feature_engineer.pkl"
            with open(fe_path, 'wb') as f:
                pickle.dump(self.feature_engineer, f)
        
        # Save metadata
        metadata = {
            'sequence_length': self.sequence_length,
            'lstm_units': self.lstm_units,
            'dropout_rate': self.dropout_rate,
            'training_metrics': self.training_metrics,
            'history': self.history
        }
        
        metadata_path = model_path.parent / f"{model_path.stem}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2, default=str)
        
        logger.info(f"Model saved to {filepath}")
    
    def load_model(self, filepath: str):
        """Load model and associated objects."""
        model_path = Path(filepath)
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {filepath}")
        
        # Load Keras model
        self.model = load_model(str(model_path))
        
        # Load feature engineer
        fe_path = model_path.parent / f"{model_path.stem}_feature_engineer.pkl"
        if fe_path.exists():
            with open(fe_path, 'rb') as f:
                self.feature_engineer = pickle.load(f)
        
        # Load metadata
        metadata_path = model_path.parent / f"{model_path.stem}_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            self.sequence_length = metadata.get('sequence_length', self.sequence_length)
            self.lstm_units = metadata.get('lstm_units', self.lstm_units)
            self.dropout_rate = metadata.get('dropout_rate', self.dropout_rate)
            self.training_metrics = metadata.get('training_metrics', {})
            self.history = metadata.get('history', {})
        
        logger.info(f"Model loaded from {filepath}")
    
    def evaluate_model(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
        """
        Evaluate model performance on test data.
        
        Args:
            X_test: Test sequences
            y_test: Test targets
            
        Returns:
            Evaluation metrics
        """
        if self.model is None:
            raise ValueError("Model not trained or loaded")
        
        # Make predictions
        predictions = self.predict(X_test)
        
        # Calculate metrics
        mae = mean_absolute_error(y_test, predictions)
        rmse = np.sqrt(mean_squared_error(y_test, predictions))
        mape = np.mean(np.abs((y_test - predictions) / y_test)) * 100
        
        # Direction accuracy (for price change predictions)
        direction_actual = np.sign(y_test)
        direction_predicted = np.sign(predictions)
        direction_accuracy = np.mean(direction_actual == direction_predicted)
        
        evaluation_metrics = {
            'mae': mae,
            'rmse': rmse,
            'mape': mape,
            'direction_accuracy': direction_accuracy,
            'n_samples': len(y_test)
        }
        
        logger.info(f"Model evaluation: {evaluation_metrics}")
        
        return evaluation_metrics
    
    def _get_model_summary(self) -> Dict[str, Any]:
        """Get model architecture summary."""
        if self.model is None:
            return {}
        
        return {
            'total_params': self.model.count_params(),
            'trainable_params': sum([tf.keras.backend.count_params(w) for w in self.model.trainable_weights]),
            'layers': len(self.model.layers),
            'lstm_layers': len([l for l in self.model.layers if 'lstm' in l.name.lower()]),
            'input_shape': self.model.input_shape,
            'output_shape': self.model.output_shape
        }
    
    def _get_model_version(self) -> str:
        """Get model version string."""
        return f"LSTM_{len(self.lstm_units)}L_{'_'.join(map(str, self.lstm_units))}U"