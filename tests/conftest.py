"""
tests/conftest.py
=================

Shared pytest fixtures, environment, and a deterministic interpreter exit.

Fix 1 — one session QApplication.
    The GUI/worker tests create QObjects (MainWindow, JobWorker/AnalyzeWorker
    QThreads, dialogs, widgets), some with live Qt signal connections.
    Per-module QApplication fixtures tore down a live application between
    test modules, so a single session-scoped `qapp` owns the app.

Fix 2 — keep-alive helper for test QObjects (`qt` fixture).
    Python's garbage collector may free a QObject at an arbitrary later
    moment, while Qt signal connections still reference it. Tests can
    register every QObject they hand to Qt via the `qt` fixture
    (`qt(worker)`, `qt(window, job)`); `_QT_KEEPALIVE` is never cleared
    while the process runs. Opt-in belt-and-suspenders for mid-run GC —
    it cannot matter after exit (Fix 3 runs no destructors at all).

Fix 3 — exit before interpreter shutdown (the CI segfault).
    Even with Fixes 1-2, CPython shutdown (Py_Finalize) tears down module
    dicts and extension state in an order PySide6 cannot survive when Qt
    objects are still reachable — observed as, after a fully green suite
    on Linux CI (twice):

        QObject: shared QObject was deleted directly. The program is
        malformed and may crash.
        Segmentation fault (core dumped)

    and reproduced locally under load as SIGSEGV/SIGABRT right after the
    summary line (the suite result was never the problem; the shutdown
    order was). Attempting explicit shiboken.delete() teardown in the
    fixture instead crashed deterministically (double-free while
    destroyQCoreApplication walked child wrappers).

    So: do no teardown at all. `pytest_sessionfinish` records the exit
    status, and an atexit callback — which CPython runs at the *start* of
    Py_Finalize, before any module or extension teardown — flushes
    stdlib streams and calls os._exit(status). No Qt object destructor
    ever runs, so the whole failure class cannot occur. Pytest output and
    the exit code are unaffected (both are complete before atexit fires).
    Caveat: other atexit callbacks (e.g. pytest-cov's data flush) are
    skipped too — fine here since CI runs plain `pytest -q` with no
    coverage; remove this hook if that ever changes.
"""

from __future__ import annotations

import atexit
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

_APP = None  # session QApplication — created on first use, never destroyed

# Every QObject the tests create and hand to Qt (signal connections, etc).
_QT_KEEPALIVE: list = []

# Exit status recorded at session end; None until pytest_sessionfinish runs
# (if it never runs — a cmdline/collection failure before the session — the
# atexit hook stays inert and normal interpreter exit proceeds).
_RECORDED_EXIT: int | None = None


def register_qt(*objects) -> None:
    """Keep Qt objects alive for the whole process (prevents GC-order crash)."""
    _QT_KEEPALIVE.extend(o for o in objects if o is not None)


def _exit_before_interpreter_shutdown() -> None:
    if _RECORDED_EXIT is None:
        return
    try:
        import sys

        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - streams may already be gone
        pass
    os._exit(_RECORDED_EXIT)


atexit.register(_exit_before_interpreter_shutdown)


def pytest_sessionfinish(session, exitstatus):
    """Record the final status for the atexit exit (see module docstring).

    Also RE-registers the atexit hook: Python runs atexit callbacks LIFO,
    and PySide6 registers its own cleanup (which walks every Qt wrapper and
    crashes on stale ones) when PySide6.QtCore is first imported — i.e.
    AFTER conftest is imported but BEFORE this hook runs. Re-registering
    here puts our os._exit() ahead of PySide's cleanup, so PySide's
    handler never executes at all.
    """
    global _RECORDED_EXIT
    try:
        _RECORDED_EXIT = int(exitstatus)
    except Exception:  # noqa: BLE001 - never fail the session over this
        pass
    atexit.register(_exit_before_interpreter_shutdown)


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the entire test session (never torn down)."""
    global _APP
    if _APP is None:
        from PySide6.QtWidgets import QApplication

        _APP = QApplication([])
    return _APP


@pytest.fixture()
def qt(qapp):
    """Register Qt objects created during a test for process-lifetime keep-alive."""
    return register_qt
