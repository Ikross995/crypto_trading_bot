#!/usr/bin/env python3
"""
Large Dataset Processing Demo

Demonstrates how to use the LargeKlinesProcessor and MLDataManager
for processing massive cryptocurrency datasets efficiently.
"""

import logging
import sys
from pathlib import Path

# Add project root to path  
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ruff: noqa: E402
from data.large_datasets.klines_processor import create_processor
from data.large_datasets.ml_data_manager import TrainingConfig, create_ml_manager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def demo_basic_processing():
    """Basic large dataset processing demonstration."""
    logger.info("=== Basic Large Dataset Processing Demo ===")

    # Initialize processor
    processor = create_processor(
        cache_dir="data/cache",
        memory_limit_mb=1024  # 1GB limit
    )

    # Example file path (user would replace with their actual file)
    klines_file = "klines_v14_0.csv"  # 7GB file mentioned by user

    if not Path(klines_file).exists():
        logger.info(f"Demo file {klines_file} not found")
        logger.info("To use with your 7GB klines file:")
        logger.info(f"  1. Place your file at: {Path.cwd() / klines_file}")
        logger.info("  2. Run this script again")
        return

    # Get basic dataset info
    logger.info("Getting dataset information...")
    info = processor.get_dataset_info(klines_file)
    logger.info(f"Dataset info: {info}")

    # Create a sample for testing
    logger.info("Creating 1% sample for testing...")
    sample_file = "data/samples/large_dataset_sample.csv"
    processor.create_training_sample(
        input_file=klines_file,
        output_file=sample_file,
        sample_ratio=0.01,  # 1% of data
        symbol_filter="BTCUSDT",
        method='random'
    )

    # Load and analyze sample
    logger.info("Loading sample data...")
    chunk_count = 0
    total_rows = 0

    for chunk in processor.load_chunk_iterator(sample_file, chunk_size=10000):
        chunk_count += 1
        total_rows += len(chunk)
        logger.info(f"Processed chunk {chunk_count}: {len(chunk)} rows")

        if chunk_count >= 3:  # Limit for demo
            break

    logger.info(f"Total processed: {total_rows:,} rows in {chunk_count} chunks")


def demo_feature_preparation():
    """Feature preparation for ML demonstration."""
    logger.info("=== Feature Preparation Demo ===")

    processor = create_processor()

    # Use sample data if available
    sample_files = [
        "data/samples/BTCUSDT_1m_sample.csv",
        "data/samples/large_dataset_sample.csv"
    ]

    sample_file = None
    for file_path in sample_files:
        if Path(file_path).exists():
            sample_file = file_path
            break

    if not sample_file:
        logger.info("No sample data found for feature preparation demo")
        return

    logger.info(f"Using sample file: {sample_file}")

    # Load sample data
    import pandas as pd
    data = pd.read_csv(sample_file).head(1000)  # First 1000 rows for demo

    # Prepare ML features
    logger.info("Preparing ML features...")
    feature_config = {
        'price_features': True,
        'technical_indicators': True,
        'volume_features': True,
        'time_features': True,
        'sequence_length': 20
    }

    try:
        features = processor.prepare_ml_features(data, feature_config)
        logger.info("Feature preparation successful!")

        for feature_name, feature_data in features.items():
            logger.info(f"  {feature_name}: shape {feature_data.shape}")

    except Exception as e:
        logger.error(f"Feature preparation failed: {e}")


def demo_ml_data_manager():
    """ML Data Manager demonstration."""
    logger.info("=== ML Data Manager Demo ===")

    # Initialize ML data manager
    ml_manager = create_ml_manager(
        cache_dir="data/ml_cache",
        memory_limit_gb=1.0
    )

    # Training configuration
    config = TrainingConfig(
        sequence_length=60,
        prediction_horizon=1,
        target_column='close',
        train_split=0.8,
        validation_split=0.1,
        test_split=0.1,
        normalize=True,
        remove_outliers=True
    )

    # Use sample data for demo
    sample_file = "data/samples/BTCUSDT_1m_sample.csv"

    if not Path(sample_file).exists():
        logger.info("Sample data not found for ML demo")
        return

    logger.info(f"Preparing training data from {sample_file}")

    try:
        # Prepare training data
        ml_manager.prepare_training_data(
            filepath=sample_file,
            config=config,
            symbol="BTCUSDT",
            sample_ratio=1.0  # Use all sample data
        )

        logger.info("Training data preparation successful!")

        # Show dataset info
        dataset_keys = list(ml_manager.datasets.keys())
        if dataset_keys:
            dataset_key = dataset_keys[0]
            info = ml_manager.get_dataset_info(dataset_key)
            logger.info(f"Dataset info: {info}")

            # Demo training batch
            logger.info("Getting training batch...")
            batch_gen = ml_manager.get_training_batch(
                dataset_key, split='train', batch_size=16, shuffle=True
            )

            X_batch, y_batch = next(batch_gen)
            logger.info(f"Training batch: X={X_batch.shape}, y={y_batch.shape}")

    except Exception as e:
        logger.error(f"ML data preparation failed: {e}")
        logger.info("This might be due to missing dependencies (pandas, numpy, etc.)")


def demo_memory_optimization():
    """Memory optimization demonstration."""
    logger.info("=== Memory Optimization Demo ===")

    create_processor(memory_limit_mb=512)  # 512MB limit

    logger.info("Memory optimization features:")
    logger.info("1. Chunked processing - processes large files in small chunks")
    logger.info("2. Memory monitoring - tracks RAM usage during processing")
    logger.info("3. Cache management - intelligent caching of processed data")
    logger.info("4. Sample generation - creates manageable subsets for testing")

    # Demo memory monitoring (optional - requires psutil)
    try:
        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / (1024 * 1024)
        logger.info(f"Current memory usage: {memory_mb:.1f} MB")
    except ImportError:
        logger.info("Memory monitoring not available (psutil not installed)")

    # Memory-efficient processing tips
    logger.info("\nMemory-efficient processing tips:")
    logger.info("- Use sample_ratio < 1.0 for initial experiments")
    logger.info("- Process data in chunks with load_chunk_iterator()")
    logger.info("- Set appropriate memory limits in processor config")
    logger.info("- Use date_range filters to process time periods")
    logger.info("- Clear datasets from memory when done: ml_manager.clear_memory()")


def demo_production_workflow():
    """Production workflow demonstration."""
    logger.info("=== Production Workflow Demo ===")

    logger.info("Recommended workflow for 7GB klines file:")
    logger.info("")

    steps = [
        "1. Initial Analysis",
        "   - Use get_dataset_info() to understand file structure",
        "   - Check available memory and set limits appropriately",
        "",
        "2. Sample Creation",
        "   - Create small samples (1-5%) for initial development",
        "   - Use create_training_sample() with different methods",
        "",
        "3. Feature Development",
        "   - Develop and test features on samples first",
        "   - Use prepare_ml_features() with various configurations",
        "",
        "4. Model Training Preparation",
        "   - Use MLDataManager with appropriate memory limits",
        "   - Process data in time-aware splits",
        "   - Save prepared datasets for reuse",
        "",
        "5. Production Processing",
        "   - Process full dataset in chunks",
        "   - Use symbol and date range filters for targeted analysis",
        "   - Monitor memory usage throughout",
        "",
        "6. Model Training",
        "   - Use get_training_batch() for efficient batch loading",
        "   - Implement early stopping and checkpointing",
        "   - Save models and scalers for production use"
    ]

    for step in steps:
        logger.info(step)

    logger.info("\nExample commands:")
    logger.info("# Create 1% sample")
    logger.info("processor.create_training_sample('klines_v14_0.csv', 'sample.csv', 0.01)")
    logger.info("")
    logger.info("# Process specific symbol and date range")
    logger.info("chunks = processor.load_chunk_iterator(")
    logger.info("    'klines_v14_0.csv',")
    logger.info("    symbol_filter='BTCUSDT',")
    logger.info("    date_filter=('2023-01-01', '2023-12-31')")
    logger.info(")")


def main():
    """Run all demonstrations."""
    logger.info("Large Dataset Processing Demonstration")
    logger.info("=" * 50)

    try:
        demo_basic_processing()
        print("\n" + "="*50 + "\n")

        demo_feature_preparation()
        print("\n" + "="*50 + "\n")

        demo_ml_data_manager()
        print("\n" + "="*50 + "\n")

        demo_memory_optimization()
        print("\n" + "="*50 + "\n")

        demo_production_workflow()

    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise

    logger.info("\nDemo completed!")
    logger.info("To use with your 7GB klines file:")
    logger.info("1. Place klines_v14_0.csv in the project root")
    logger.info("2. Adjust memory limits based on your system")
    logger.info("3. Start with small samples (1-5%) for initial testing")
    logger.info("4. Scale up processing as needed")


if __name__ == "__main__":
    main()
