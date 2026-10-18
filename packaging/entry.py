"""
PyInstaller entry point for OptiCipher Desktop.

Kept separate from app/main.py so packaging concerns (frozen-path behaviour)
live in one tiny module the spec can point at.
"""

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
