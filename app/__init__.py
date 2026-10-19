"""
app
===

OptiCipher Desktop — the PySide6 GUI over the OptiCipher library.
"""

__all__ = ["main"]

#: The desktop application's version. Kept in step with pyproject.toml.
__version__ = "1.3.0"


def main() -> int:
    from .main import main as _main

    return _main()
