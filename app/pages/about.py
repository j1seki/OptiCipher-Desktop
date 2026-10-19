"""
app.pages.about
===============

Version, provenance and the honest limits of the tool.

The threat-model paragraph is deliberately here and not hidden: this is a
research/educational tool, and a user deserves to know that before they
encrypt something that matters to them.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import GAP_MD
from ..widgets import Card, GhostButton, InfoRow
from .base import BasePage

REPOSITORY = "https://github.com/j1seki/OptiCipher-Desktop"
UPSTREAM = "https://github.com/bio-colab/OptiCipher"


class AboutPage(BasePage):
    """Version, provenance and limits."""

    key = "about"
    title = "About"
    subtitle = "What this application is, where it comes from, and what it does not do."

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()

    def _build(self) -> None:
        details = Card("OptiCipher Desktop", "A desktop front end for the OptiCipher library.")
        self.rows = {}
        for key, label in (
            ("app_version", "Desktop version"),
            ("lib_version", "OptiCipher library"),
            ("license", "License"),
            ("backend", "Acceleration"),
            ("upstream", "Upstream project"),
            ("fork", "This fork"),
        ):
            row = InfoRow(label, "—")
            self.rows[key] = row
            details.body.addWidget(row)
        self.content.addWidget(details)

        what = Card("What it does", "")
        body = QLabel(
            "OptiCipher performs <b>perceptual (optical) image encryption</b>: "
            "the result is still a normal PNG that opens in any image viewer, "
            "but its pixels are scrambled and diffused, and everything needed "
            "to restore it is embedded in the file itself. The ciphertext is "
            "authenticated with HMAC-SHA256, so a modified file is detected "
            "rather than silently mis-decrypted."
        )
        body.setWordWrap(True)
        body.setObjectName("Muted")
        what.body.addWidget(body)
        self.content.addWidget(what)

        limits = Card("Limits", "Please read this before relying on it.")
        limits_body = QLabel(
            "This is a research and educational tool. The passphrase is the only "
            "key: there is no recovery, no escrow and no back door. A file "
            "encrypted with a lost passphrase is gone. The image format is PNG, "
            "so store ciphertext only in a lossless format — re-encoding it as "
            "JPEG will destroy the pixel data the restoration depends on."
        )
        limits_body.setWordWrap(True)
        limits_body.setObjectName("Muted")
        limits.body.addWidget(limits_body)
        self.content.addWidget(limits)

        attribution = Card("Attribution", "")
        attr = QLabel(
            "OptiCipher Desktop is a fork of the OptiCipher library by "
            "bio-colab, which is distributed under the MIT License. The "
            "desktop application, the SFTP output support and this interface "
            "were added by the fork's authors, also under MIT."
        )
        attr.setWordWrap(True)
        attr.setObjectName("Muted")
        attribution.body.addWidget(attr)

        copy_btn = GhostButton("Copy repository link")
        copy_btn.setToolTip(
            "Copy this project's GitHub URL to the clipboard"
        )
        copy_btn.clicked.connect(self._copy_repository)
        attribution.body.addWidget(copy_btn)
        self.copy_btn = copy_btn
        self.content.addWidget(attribution)

    def _copy_repository(self) -> None:
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(REPOSITORY)
        self.copy_btn.setText("Copied ✓")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy repository link"))

    def refresh(self) -> None:
        from opticipher import __version__ as lib_version
        from opticipher import accel

        from .. import __version__ as app_version

        backend = accel.get_backend()
        info = backend.info()
        detail = info.get("detail", backend.name) or backend.name
        self.rows["app_version"].set_value(app_version)
        self.rows["lib_version"].set_value(lib_version)
        self.rows["license"].set_value("MIT")
        self.rows["backend"].set_value(detail)
        self.rows["upstream"].set_value(UPSTREAM)
        self.rows["fork"].set_value(REPOSITORY)
