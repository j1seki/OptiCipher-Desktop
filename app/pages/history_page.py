"""
app.pages.history_page
======================

The session activity log.

Honesty note: OptiCipher keeps **no** permanent history. A tool whose job
is to protect files should not quietly record what you did with them. This
page therefore shows the operations performed since the application started,
in memory, and says exactly that — so nobody mistakes it for an audit trail
that survives a restart.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import GAP_MD
from ..widgets import Card, EmptyState, SecondaryButton
from .base import BasePage

_COLUMNS = ("Time", "Operation", "File", "Result", "Detail")


class HistoryPage(BasePage):
    """What happened in this session."""

    key = "history"
    title = "History"
    subtitle = (
        "Operations performed since the application started. This log lives "
        "in memory only — it is never written to disk and disappears when the "
        "application closes."
    )

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()

    def _build(self) -> None:
        card = Card("Session activity", "Newest first.")
        clear = SecondaryButton("Clear log")
        clear.setObjectName("history_clear")
        clear.setToolTip(
            "Remove every entry from this session's log (nothing on disk is "
            "affected)"
        )
        clear.clicked.connect(self._clear)
        card.set_header_widget(clear)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch
        )
        self.table.setMinimumHeight(240)
        card.body.addWidget(self.table)

        self.empty = EmptyState(
            "clock",
            "Nothing recorded yet",
            "Encrypt, decrypt or verify a file and it will appear here — for "
            "this session only.",
        )
        card.body.addWidget(self.empty)

        note = QLabel(
            "Tip: the log is intentionally session-scoped. OptiCipher does not "
            "keep a permanent record of the files you process."
        )
        note.setObjectName("Faint")
        note.setWordWrap(True)
        card.body.addWidget(note)

        self.content.addWidget(card, 1)
        self._card = card

    # -- behaviour ----------------------------------------------------------
    def refresh(self) -> None:
        history = getattr(self.window, "history", None)
        entries = history.recent(100) if history is not None else []

        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = (
                entry.time_text,
                entry.kind,
                entry.subject,
                "Succeeded" if entry.status == "ok" else "Failed",
                entry.detail or (entry.output or ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        self.empty.setVisible(not entries)
        self.table.setVisible(bool(entries))

    def _clear(self) -> None:
        history = getattr(self.window, "history", None)
        if history is not None:
            history.clear()
        self.refresh()
