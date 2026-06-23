"""
__main__.py
===========

Allows running OptiCipher as a module:  `python -m opticipher ...`

It simply delegates to the CLI's main() and propagates the exit code.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
