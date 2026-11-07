"""Entry point for PyInstaller and for double-click starts (python run_alles.py)."""
import sys

from alles.app import main

if __name__ == "__main__":
    sys.exit(main())
