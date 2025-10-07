"""
Data module constants (compatibility placeholder).

This module exists to ensure backward compatibility and prevent
"No module named 'data.constants'" errors if referenced in cached
files or legacy configurations.

All constants are now in core.constants for better organization.
"""

# Import all constants from core.constants for compatibility
# Deprecated warning for direct usage
import warnings

from core.constants import *  # noqa: F403

warnings.warn(
    "data.constants is deprecated. Use core.constants instead.",
    DeprecationWarning,
    stacklevel=2
)
