#!/usr/bin/env python3
"""
Fix CLI Configuration Loading

This script fixes the CLI to properly load .env.testnet files
and integrate with the real API client.
"""

import os
import shutil
from datetime import datetime

def fix_cli_config():
    """Fix CLI to support config file loading."""
    
    # Read current CLI file
    if not os.path.exists('cli_updated.py'):
        print("❌ cli_updated.py not found")
        return
    
    with open('cli_updated.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix the paper command function signature (remove duplicate config parameters)
    content = content.replace(
        '    config_file: str | None = typer.Option(\n        None, "--config", help="Config file path"\n    ),',
        ''
    )
    
    # Fix the reference to config_file in load_config call
    content = content.replace(
        'config = load_config(config_file)',
        'config = load_config(None)'  # Use None since we handle config loading above
    )
    
    # Backup original
    backup_name = f'cli_updated.py.backup_config_fix_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2('cli_updated.py', backup_name)
    
    # Write fixed version
    with open('cli_updated.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ Fixed CLI configuration loading")
    print(f"   - Backup created: {backup_name}")
    print("   - Removed duplicate --config parameter")
    print("   - Fixed config_file reference")


def test_cli_syntax():
    """Test the fixed CLI syntax."""
    try:
        import subprocess
        result = subprocess.run(['python', '-m', 'py_compile', 'cli_updated.py'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ CLI syntax validation passed")
        else:
            print("❌ CLI syntax error:")
            print(result.stderr)
    except Exception as e:
        print(f"❌ Error testing CLI syntax: {e}")


def main():
    """Main fix function."""
    
    print("🔧 FIXING CLI CONFIGURATION LOADING")
    print("=" * 50)
    print("Problem: Duplicate --config parameters and config_file reference")
    print("Solution: Fix CLI parameter handling for .env.testnet")
    print("=" * 50)
    
    fix_cli_config()
    test_cli_syntax()
    
    print("\\n" + "=" * 50)
    print("🎯 TESTING:")
    print("python cli_updated.py paper --config .env.testnet --symbols BTCUSDT --verbose")
    print("Should now load .env.testnet and use real API if configured")
    print("=" * 50)


if __name__ == "__main__":
    main()