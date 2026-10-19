"""
tests/conftest.py
================

Shared pytest fixtures and environment.

The `qapp` fixture is SESSION-scoped and deliberately never destroyed:
creating one QApplication per GUI test module (and letting each module's
fixture teardown destroy it) made Qt tear down a live application between
modules, which segfaulted the interpreter at exit on Linux CI
("QObject: shared QObject was deleted directly" → SIGSEGV after a fully
green suite). One app for the whole session, owned by a module-level
global until process exit, is the stable pattern.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

_APP = None  # never destroyed — see module docstring


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the entire test session (never torn down)."""
    global _APP
    if _APP is None:
        from PySide6.QtWidgets import QApplication

        _APP = QApplication([])
    return _APP
