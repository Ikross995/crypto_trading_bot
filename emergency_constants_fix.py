def fix_missing_constants():
    """Add missing constants to core/constants.py"""
    print("🔧 Emergency fix for missing constants...")
    
    # Read current constants
    constants_file = "core/constants.py"
    with open(constants_file, 'r', encoding='utf-8') as f:
        current_content = f.read()
    
    print("📋 Current constants found:")
    if "OrderStatus" in current_content:
        print("✅ OrderStatus already exists")
    else:
        print("❌ OrderStatus MISSING")
        
    if "Regime" in current_content:
        print("✅ Regime already exists")
    else:
        print("❌ Regime MISSING")
        
    if "SignalDirection" in current_content:
        print("✅ SignalDirection already exists")
    else:
        print("❌ SignalDirection MISSING")
    
    # Add missing constants
    missing_constants = '''

class OrderStatus(Enum):
    """Order status types."""
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Regime(Enum):
    """Market regime types."""
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    STABLE = "STABLE"


class SignalDirection(Enum):
    """Signal direction types."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    CLOSE = "CLOSE"
'''
    
    # Update __all__ exports
    updated_exports = '''
# Explicit exports for better compatibility
__all__ = [
    "TradingMode",
    "OrderSide", 
    "OrderType",
    "OrderStatus",
    "PositionSide",
    "SignalType",
    "ExitReason",
    "Regime",
    "SignalDirection",
]'''
    
    # Add missing constants if not present
    needs_update = False
    if "OrderStatus" not in current_content:
        needs_update = True
        # Insert before __all__
        if "__all__" in current_content:
            current_content = current_content.replace(
                "# Explicit exports for better compatibility\n__all__",
                missing_constants + "\n\n# Explicit exports for better compatibility\n__all__"
            )
        else:
            current_content += missing_constants
    
    # Update exports
    if "__all__" in current_content and ("OrderStatus" not in current_content or "Regime" not in current_content):
        # Replace the __all__ section
        lines = current_content.split('\n')
        new_lines = []
        in_all_section = False
        
        for line in lines:
            if line.strip().startswith('__all__'):
                in_all_section = True
                new_lines.extend(updated_exports.split('\n'))
                continue
            elif in_all_section and line.strip() == ']':
                in_all_section = False
                continue
            elif in_all_section:
                continue
            else:
                new_lines.append(line)
        
        current_content = '\n'.join(new_lines)
        needs_update = True
    
    if needs_update:
        # Write updated content
        with open(constants_file, 'w', encoding='utf-8') as f:
            f.write(current_content)
        print("✅ Added missing constants to core/constants.py")
        
        # Verify imports work
        try:
            from core.constants import OrderStatus, Regime, SignalDirection, SignalType, PositionSide
            print("✅ All constants import successfully")
            return True
        except ImportError as e:
            print(f"❌ Import still failing: {e}")
            return False
    else:
        print("✅ All constants already present")
        return True

if __name__ == "__main__":
    success = fix_missing_constants()
    if success:
        print("🎉 Constants fix completed successfully!")
    else:
        print("❌ Constants fix failed, manual intervention needed")