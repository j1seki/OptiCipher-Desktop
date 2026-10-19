"""
app.pages.overview
==================

The landing screen.

It answers three questions and nothing else:

  * What is this application?  (a short, factual description)
  * What can I do right now?   (three quick actions that really work)
  * What is this machine able to do?  (the real compute backend and its
    limits, read from the acceleration layer)

It deliberately does **not** show a security score, a "your files are safe"
badge, or a success count it cannot back up. What it does show about
activity is the real, session-scoped activity log.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import device as _device
from .. import icons
from ..theme import GAP_LG, GAP_MD, GAP_SM
from ..widgets import Card, EmptyState, InfoRow, SectionTitle, StatTile
from .base import BasePage


class OverviewPage(BasePage):
    """The home screen."""

    key = "overview"
    title = "Overview"
    subtitle = (
        "Perceptual image encryption: your image stays a normal, viewable PNG "
        "that only the right passphrase can turn back into the original."
    )

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()

    def _build(self) -> None:
        # -- quick actions ---------------------------------------------------
        actions = Card("Get started", "Jump straight into a task.")
        row = QHBoxLayout()
        row.setSpacing(GAP_MD)
        self.quick_buttons = []
        for key, label, glyph, tip in (
            ("encrypt", "Encrypt images", "lock", "Protect images with a passphrase"),
            ("decrypt", "Decrypt an image", "unlock", "Restore an encrypted image"),
            ("verify", "Verify integrity", "shield", "Check a file without restoring it"),
        ):
            button = QPushButton(f"  {label}")
            button.setObjectName("QuickAction")
            button.setIcon(icons.icon(glyph, "#38D6A3", 20))
            button.setIconSize(QSize(20, 20))
            button.setToolTip(tip)
            button.setAccessibleName(label)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _c=False, k=key: self._navigate(k))
            self.quick_buttons.append((button, glyph))
            row.addWidget(button, 1)
        actions.body.addLayout(row)
        self.content.addWidget(actions)

        # -- two columns: environment + session activity --------------------
        columns = QHBoxLayout()
        columns.setSpacing(GAP_MD)

        env = Card("This machine", "Where the work runs, and its limits.")
        self.env_rows = {}
        for key, label in (
            ("backend", "Compute backend"),
            ("calibration", "Backend calibration"),
            ("threads", "Worker threads"),
            ("ram", "RAM budget"),
            ("system_ram", "System RAM"),
            ("platform", "Platform"),
            ("version", "OptiCipher library"),
        ):
            row = InfoRow(label, "—")
            self.env_rows[key] = row
            env.body.addWidget(row)
        columns.addWidget(env, 1)

        activity = Card("Session activity", "What happened since the app started.")
        self.stats = {
            "total": StatTile("Operations"),
            "ok": StatTile("Succeeded"),
            "failed": StatTile("Failed"),
        }
        stats_row = QHBoxLayout()
        stats_row.setSpacing(GAP_LG)
        for tile in self.stats.values():
            stats_row.addWidget(tile)
        activity.body.addLayout(stats_row)

        self.activity_empty = EmptyState(
            "clock",
            "No operations yet",
            "This build keeps no permanent history: everything you do is "
            "logged in memory for this session only, and never written to disk.",
        )
        activity.body.addWidget(self.activity_empty)

        self.activity_list = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_list)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(4)
        activity.body.addWidget(self.activity_list)
        self.activity_list.setVisible(False)

        columns.addWidget(activity, 1)
        self.content.addLayout(columns, 1)

    # -- behaviour ----------------------------------------------------------
    def recolor(self, palette) -> None:
        """Re-tint the quick-action icons when the theme changes."""
        for button, glyph in self.quick_buttons:
            button.setIcon(icons.icon(glyph, palette.accent, 20))

    def _navigate(self, key: str) -> None:
        if self.window is not None:
            self.window.navigate(key)

    def refresh(self) -> None:
        from opticipher import __version__ as lib_version
        from opticipher import accel

        cfg = accel.get_config()
        backend = accel.get_backend()
        info = backend.info()
        detail = info.get("detail", backend.name) or backend.name
        calibration = info.get("calibration", "")
        self.env_rows["backend"].set_value(detail)
        self.env_rows["calibration"].set_value(calibration or "not measured")
        self.env_rows["threads"].set_value(str(cfg["resolved_threads"]))
        self.env_rows["ram"].set_value(f"{cfg['resolved_ram_mb']} MiB")
        ram = _device.total_ram_mb()
        self.env_rows["system_ram"].set_value(
            f"{ram / 1024:.1f} GiB" if ram else "unknown"
        )
        self.env_rows["platform"].set_value(_device.platform_summary())
        self.env_rows["version"].set_value(lib_version)

        self._refresh_activity()

    def _refresh_activity(self) -> None:
        history = getattr(self.window, "history", None)
        if history is None:
            return
        counts = history.counts()
        self.stats["total"].set_value(str(counts["total"]))
        self.stats["ok"].set_value(str(counts["ok"]))
        self.stats["failed"].set_value(str(counts["failed"]))

        entries = history.recent(6)
        # Rebuild the small activity list (a handful of rows — cheap).
        while self.activity_layout.count():
            item = self.activity_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for entry in entries:
            line = QLabel(
                f"{entry.time_text}   {entry.kind}   {entry.subject}   —   "
                f"{'ok' if entry.status == 'ok' else entry.detail or 'failed'}"
            )
            line.setObjectName("Muted")
            line.setWordWrap(True)
            self.activity_layout.addWidget(line)
        has_entries = bool(entries)
        self.activity_empty.setVisible(not has_entries)
        self.activity_list.setVisible(has_entries)
