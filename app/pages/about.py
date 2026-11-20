"""
app.pages.about
===============

Version, provenance and the honest limits of the tool.

The threat-model paragraph is deliberately here and not hidden: this is a
research/educational tool, and a user deserves to know that before they
encrypt something that matters to them.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import GAP_MD
from ..widgets import Card, GhostButton, InfoRow
from .base import BasePage

REPOSITORY = "https://github.com/j1seki/OptiCipher-Desktop"
UPSTREAM = "https://github.com/bio-colab/OptiCipher"
RELEASE_API = "https://api.github.com/repos/j1seki/OptiCipher-Desktop/releases/latest"


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
        self.network = QNetworkAccessManager(self)
        self.update_button = GhostButton("Check for updates")
        self.update_button.setToolTip("Compare this app with the latest GitHub release")
        self.update_button.clicked.connect(self._check_update)
        self.update_status = QLabel()
        self.update_status.setWordWrap(True)
        self.download = GhostButton("Open release downloads")
        self.download.setToolTip("Open the official release page in your browser")
        self.download.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"{REPOSITORY}/releases/latest")))
        self.download.hide()
        details.body.addWidget(self.update_button)
        details.body.addWidget(self.update_status)
        details.body.addWidget(self.download)

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

    def _check_update(self) -> None:
        self.update_button.setEnabled(False)
        self.update_status.setText("Checking for updates…")
        self.download.hide()
        request = QNetworkRequest(QUrl(RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", b"OptiCipherDesktop")
        request.setTransferTimeout(15000)
        reply = self.network.get(request)
        reply.finished.connect(self._show_update)

    def _show_update(self) -> None:
        from .. import __version__

        reply = self.sender()
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            tag = json.loads(bytes(reply.readAll()))["tag_name"]
            match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
            if match is None:
                raise ValueError("The release version is unavailable.")
            version = tuple(map(int, match.groups()))
            if version > tuple(map(int, __version__.split("."))):
                self.update_status.setText(f"OptiCipher {tag} is available.")
                self.download.show()
            else:
                self.update_status.setText(f"OptiCipher {__version__} is up to date.")
        except (KeyError, TypeError, ValueError) as error:
            self.update_status.setText(f"Update check failed. {error}")
        finally:
            reply.deleteLater()
            self.update_button.setEnabled(True)

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
