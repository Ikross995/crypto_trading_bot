"""
Large Dataset Processing Module

Memory-efficient processing for massive cryptocurrency datasets,
specifically designed for multi-GB klines files.
"""

from .klines_processor import LargeKlinesProcessor, create_processor
from .ml_data_manager import MLDataManager, TrainingConfig, create_ml_manager

__all__ = [
    'LargeKlinesProcessor',
    'create_processor', 
    'MLDataManager',
    'TrainingConfig',
    'create_ml_manager'
]

__version__ = "1.0.0"