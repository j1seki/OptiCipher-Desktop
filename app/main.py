"""
app.main
========

Entry point for the OptiCipher Desktop application.

Run with:
    python -m app.main
or, once installed/packaged, the `opticipher-desktop` console/bundle entry.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from .window import MainWindow


def main() -> int:
    # CI smoke mode: construct the full window offscreen, then exit.
    # Lets the packaged artifact prove it launches on a headless runner.
    if "--smoke" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        app.processEvents()
        print("SMOKE OK")
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("OptiCipher Desktop")
    app.setOrganizationName("bio-colab")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
