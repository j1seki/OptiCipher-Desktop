"""
app.settings
============

Persistent application settings (QSettings) and their one-way application to
the acceleration layer.

The GUI never talks to `opticipher.accel.configure` piecemeal: it saves
settings here, then calls `apply_to_accel()` once, so the library's compute
behaviour always mirrors what the user sees in the settings dialog.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSettings

from opticipher import accel
from opticipher import keys as _keys

ORG = "bio-colab"
APP = "OptiCipherDesktop"


class AppSettings:
    """Typed wrapper over the QSettings store."""

    def __init__(self) -> None:
        self._s = QSettings(ORG, APP)

    # -- compute ------------------------------------------------------------
    @property
    def device(self) -> str:
        return str(self._s.value("compute/device", "auto"))

    @device.setter
    def device(self, value: str) -> None:
        self._s.setValue("compute/device", value)

    @property
    def threads(self) -> int:
        """0 means 'auto' (one thread per CPU core)."""
        return int(self._s.value("compute/threads", 0))

    @threads.setter
    def threads(self, value: int) -> None:
        self._s.setValue("compute/threads", int(value))

    @property
    def ram_budget_mb(self) -> int:
        return int(self._s.value("compute/ram_budget_mb", 512))

    @ram_budget_mb.setter
    def ram_budget_mb(self, value: int) -> None:
        self._s.setValue("compute/ram_budget_mb", int(value))

    # -- crypto -------------------------------------------------------------
    @property
    def iterations(self) -> int:
        return int(self._s.value("crypto/iterations", _keys.DEFAULT_ITERATIONS))

    @iterations.setter
    def iterations(self, value: int) -> None:
        self._s.setValue("crypto/iterations", int(value))

    # -- paths --------------------------------------------------------------
    @property
    def last_dir(self) -> str:
        return str(self._s.value("paths/last", ""))

    @last_dir.setter
    def last_dir(self, value: str) -> None:
        self._s.setValue("paths/last", value)

    @property
    def output_dir(self) -> str:
        """Empty string means 'next to the input file'."""
        return str(self._s.value("paths/output", ""))

    @output_dir.setter
    def output_dir(self, value: str) -> None:
        self._s.setValue("paths/output", value)

    # -- sync to library ----------------------------------------------------
    def apply_to_accel(self) -> None:
        """
        Push the saved compute settings into the acceleration layer.

        `threads=0` maps to None, which the accel layer resolves to the
        machine's CPU count.
        """
        accel.configure(
            device=self.device,
            threads=self.threads if self.threads > 0 else None,
            ram_budget_mb=self.ram_budget_mb,
        )
