# install_site_sig_guard.py
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "sitecustomize.py"

CONTENT = """# Auto-installed by install_site_sig_guard.py
# This file is imported automatically by Python (via 'site') if present on sys.path.
# It prevents NameError for legacy 'sig' usage across any module.

import builtins

# define only if not already defined to avoid side effects
if not hasattr(builtins, "sig"):
    builtins.sig = None
if not hasattr(builtins, "trade_signal"):
    builtins.trade_signal = None

# optional: a tiny breadcrumb to stdout so we know it's active
try:
    print("\\u2705 sitecustomize: global 'sig' guard active")
except Exception:
    pass
"""

def main():
    SITE.write_text(CONTENT, encoding="utf-8")
    print(f"✅ Created {SITE.name} in {SITE.parent}")
    print("   Python will auto-import it on start (via 'site').")

if __name__ == "__main__":
    main()
