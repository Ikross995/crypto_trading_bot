#!/usr/bin/env python3
"""
Fix User Config - Add Missing Properties

This script identifies and fixes missing properties in the user's Config class
that are required for the updated CLI to work properly.
"""

import os
import re
from pathlib import Path


def find_config_file():
    """Find the user's config.py file."""
    possible_paths = [
        "core/config.py",
        "../core/config.py", 
        "../../core/config.py",
        "config.py"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    return None


def check_config_properties(config_path):
    """Check which properties are missing from the config."""
    if not os.path.exists(config_path):
        return None, []
        
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_properties = [
        'max_daily_loss',
        'close_positions_on_exit'
    ]
    
    missing = []
    for prop in required_properties:
        # Look for @property decorator followed by the property name
        if f"def {prop}(" not in content:
            missing.append(prop)
    
    return content, missing


def generate_fix():
    """Generate the fix code that needs to be added to Config class."""
    fix_code = '''
    @property
    def max_daily_loss(self) -> float:
        """Get max daily loss for compatibility."""
        return self.max_daily_loss_pct

    @property
    def close_positions_on_exit(self) -> bool:
        """Whether to close positions on bot exit."""
        return True  # Default behavior
'''
    return fix_code


def show_manual_fix():
    """Show manual instructions for fixing the config."""
    print("""
🔧 MANUAL FIX INSTRUCTIONS
==========================

Your Config class is missing required properties. Add this code to your core/config.py:

1. Find your Config class definition
2. Add these properties INSIDE the class (before the last line):

""")
    print(generate_fix())
    print("""
3. The complete fix should be added just before the closing of your Config class.

Example placement:
```python
class Config(BaseModel):
    # ... existing fields ...
    
    # Feature flags (aliases for compatibility)
    @property
    def use_lstm(self) -> bool:
        return self.lstm_enable

    # ADD THE NEW PROPERTIES HERE:
    @property
    def max_daily_loss(self) -> float:
        \"\"\"Get max daily loss for compatibility.\"\"\"
        return self.max_daily_loss_pct

    @property
    def close_positions_on_exit(self) -> bool:
        \"\"\"Whether to close positions on bot exit.\"\"\"
        return True  # Default behavior

    # ... rest of the class ...
```

After adding this, your CLI should work without the AttributeError!
""")


def automatic_fix(config_path, content):
    """Attempt to automatically fix the config file."""
    try:
        # Find the end of the Config class
        # Look for the last method or property before class ends
        
        # Strategy: Find a good insertion point before class ends
        # Look for common patterns like "def parse_" or "@classmethod"
        
        fix_code = generate_fix()
        
        # Try to find insertion point - look for existing @property methods
        property_pattern = r'(@property\s+def\s+\w+.*?\n\s+return.*?\n)'
        properties = re.findall(property_pattern, content, re.DOTALL)
        
        if properties:
            # Insert after the last property
            last_property = properties[-1]
            insert_point = content.rfind(last_property) + len(last_property)
            new_content = content[:insert_point] + fix_code + content[insert_point:]
        else:
            # Try to find a good insertion point
            # Look for methods like has_api_credentials or parse_dca_ladder
            method_patterns = [
                r'(def has_api_credentials.*?\n        return.*?\n)',
                r'(def parse_dca_ladder.*?\n        return.*?\n)',
                r'(@classmethod\s+def validate_mode.*?\n        return.*?\n)'
            ]
            
            for pattern in method_patterns:
                matches = re.findall(pattern, content, re.DOTALL)
                if matches:
                    last_match = matches[-1]
                    insert_point = content.rfind(last_match) + len(last_match)
                    new_content = content[:insert_point] + fix_code + content[insert_point:]
                    break
            else:
                print("❌ Could not find good insertion point for automatic fix")
                return False
        
        # Backup original file
        backup_path = config_path + '.backup'
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"📋 Created backup: {backup_path}")
        
        # Write the fixed file
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ Automatically fixed {config_path}")
        return True
        
    except Exception as e:
        print(f"❌ Automatic fix failed: {e}")
        return False


def main():
    """Main function."""
    print("🔍 Checking Config for Missing Properties...")
    print("=" * 50)
    
    config_path = find_config_file()
    if not config_path:
        print("❌ Could not find core/config.py file")
        print("Make sure you're running this from the project directory")
        show_manual_fix()
        return
    
    print(f"📁 Found config file: {config_path}")
    
    content, missing = check_config_properties(config_path)
    if content is None:
        print("❌ Could not read config file")
        return
    
    if not missing:
        print("✅ All required properties are present!")
        return
    
    print(f"❌ Missing properties: {missing}")
    print()
    
    # Ask user if they want automatic fix
    try:
        response = input("Do you want to attempt automatic fix? (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            if automatic_fix(config_path, content):
                print()
                print("🎉 Fix applied successfully!")
                print("Now try running your CLI command again:")
                print("python cli_updated.py paper --symbols BTCUSDT --timeframe 1m")
            else:
                print()
                show_manual_fix()
        else:
            show_manual_fix()
            
    except KeyboardInterrupt:
        print("\n\nOperation cancelled.")
        show_manual_fix()


if __name__ == "__main__":
    main()