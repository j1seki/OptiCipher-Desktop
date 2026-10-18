"""
app
===

OptiCipher Desktop — the PySide6 GUI over the OptiCipher library.
"""

__all__ = ["main"]


def main() -> int:
    from .main import main as _main

    return _main()
