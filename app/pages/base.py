"""
app.pages.base
==============

The common shape of every page.

A page owns its own header (title + description) and a content area. The
window places it in a stack and shows one at a time. Pages never talk to
each other; they emit signals or call back into the window.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..theme import GAP_LG, GAP_MD
from ..widgets import PageHeader


class BasePage(QWidget):
    """A page with a header and a content area."""

    #: Navigation key (matches the sidebar entry).
    key: str = ""
    #: Header title.
    title: str = ""
    #: One-line description shown under the title.
    subtitle: str = ""

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.window = window
        self.header = PageHeader(self.title, self.subtitle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(GAP_LG, GAP_MD, GAP_LG, GAP_LG)
        layout.setSpacing(GAP_MD)
        layout.addWidget(self.header)
        self.content = QVBoxLayout()
        self.content.setSpacing(GAP_MD)
        layout.addLayout(self.content, 1)

    # -- lifecycle ----------------------------------------------------------
    def refresh(self) -> None:
        """Called when the page becomes visible (re-read live state)."""
