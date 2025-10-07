#!/usr/bin/env python3
"""
Fix CLI Final - Complete CLI Parameter Fix

This script properly fixes the CLI to support --config parameter.
"""

import os
import shutil
from datetime import datetime

def fix_cli_completely():
    """Fix CLI completely with proper --config parameter."""
    
    # Read current CLI
    with open('cli_updated.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find and fix the paper function signature
    paper_start = content.find('@app.command()\ndef paper(')
    if paper_start == -1:
        print("❌ Could not find paper function")
        return
    
    # Find the end of the function signature
    signature_end = content.find(') -> None:', paper_start)
    if signature_end == -1:
        print("❌ Could not find end of function signature")
        return
    
    # Extract everything before the signature
    before_signature = content[:paper_start]
    
    # Extract everything after the signature
    after_signature = content[signature_end + len(') -> None:'):]
    
    # Create the correct function signature
    new_signature = '''@app.command()
def paper(
    symbols: list[str] | None = typer.Option(
        None, "--symbols", "-s", help="Trading symbols"
    ),
    timeframe: str | None = typer.Option(
        None, "--timeframe", "-t", help="Timeframe"
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Configuration file path (e.g., .env.testnet)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
) -> None:'''
    
    # Rebuild the content
    fixed_content = before_signature + new_signature + after_signature
    
    # Backup current version
    backup_name = f'cli_updated.py.backup_final_fix_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2('cli_updated.py', backup_name)
    
    # Write fixed version
    with open('cli_updated.py', 'w', encoding='utf-8') as f:
        f.write(fixed_content)
    
    print("✅ Fixed CLI completely")
    print(f"   - Backup created: {backup_name}")
    print("   - Proper --config parameter restored")


def test_cli():
    """Test CLI functionality."""
    try:
        # Test syntax
        import subprocess
        result = subprocess.run(['python', '-m', 'py_compile', 'cli_updated.py'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ CLI syntax validation passed")
        else:
            print("❌ CLI syntax error:")
            print(result.stderr)
            return False
            
        # Test help message
        result = subprocess.run(['python', 'cli_updated.py', 'paper', '--help'], 
                              capture_output=True, text=True)
        if '--config' in result.stdout:
            print("✅ --config parameter is available in help")
        else:
            print("❌ --config parameter not found in help")
            print("Help output:", result.stdout)
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Error testing CLI: {e}")
        return False


def main():
    """Main fix function."""
    
    print("🔧 FINAL CLI FIX - RESTORE --CONFIG PARAMETER")
    print("=" * 60)
    print("Problem: --config parameter was accidentally removed completely")
    print("Solution: Restore proper function signature with --config")
    print("=" * 60)
    
    fix_cli_completely()
    
    if test_cli():
        print("\\n" + "=" * 60)
        print("🎯 SUCCESS! CLI is now ready for testing:")
        print("python cli_updated.py paper --config .env.testnet --symbols BTCUSDT --verbose")
        print("=" * 60)
    else:
        print("\\n❌ CLI fix failed - check errors above")


if __name__ == "__main__":
    main()