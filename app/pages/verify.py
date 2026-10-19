"""
app.pages.verify
================

The integrity-verification screen.

What this screen may and may not claim
--------------------------------------
A file's own hash proves only that the file did not change since *you* took
the hash. It says nothing about who produced it. OptiCipher's ciphertexts
carry an HMAC-SHA256 tag over the ciphertext and the header, keyed by the
passphrase — so with the passphrase, "verified" means "this is exactly what
that passphrase authenticated". Without it, the screen says the format was
recognised and explicitly states that nothing was authenticated.

The states shown here are exactly the states the backend can produce
(``opticipher.core.verify_image``); the page never invents one.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import GAP_MD, GAP_SM
from ..widgets import (
    Card,
    Field,
    FileList,
    InfoRow,
    PasswordField,
    PreviewPanel,
    PrimaryButton,
    SecondaryButton,
    StatusBadge,
)
from .base import BasePage

PASSPHRASE_TIP = (
    "Optional. With the passphrase, the file's authentication tag is "
    "verified — that is the check that proves the file was not modified. "
    "Leave it empty to inspect the format only (no integrity claim)."
)

#: Backend status -> (label, badge variant, hint)
_STATES = {
    "verified": ("Verified", "success", "The authentication tag matches."),
    "failed": ("Verification failed", "error", "The tag did not match."),
    "malformed": ("Corrupted or malformed", "error", "Not a usable ciphertext."),
    "unsupported_format": ("Unsupported format", "warning", "No OptiCipher header."),
    "unsupported_version": ("Unsupported version", "warning", "Newer format."),
    "unauthenticated": ("Not verified", "info", "Format only — no passphrase."),
}


class VerifyPage(BasePage):
    """Check an encrypted file's format and integrity."""

    key = "verify"
    title = "Verify integrity"
    subtitle = (
        "Check an encrypted file without restoring it. With the passphrase, "
        "the file's authentication tag is verified — that is the check that "
        "proves the ciphertext was not modified after it was encrypted."
    )

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()

    def _build(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSplitter

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        # -- left: what to check --------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(GAP_MD)

        file_card = Card("File", "Pick the encrypted file to check.")
        self.files = FileList()
        file_card.body.addWidget(self.files)
        left_layout.addWidget(file_card)

        key_card = Card("Passphrase", "Optional — needed for a real integrity check.")
        self.pass_field = PasswordField("Passphrase (optional)", PASSPHRASE_TIP)
        key_card.body.addWidget(Field("Passphrase", self.pass_field, "", self))
        self.pass_field.setToolTip(PASSPHRASE_TIP)
        self.pass_field.edit.setToolTip(PASSPHRASE_TIP)
        left_layout.addWidget(key_card)
        left_layout.addStretch(1)

        splitter.addWidget(left)
        # -- right: the verdict ----------------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(GAP_MD)

        self.preview = PreviewPanel(show_result=False)
        right_layout.addWidget(self.preview, 1)

        verdict = Card("Result", "The state of the last check.")
        self.status_badge = StatusBadge("Idle", "neutral")
        self.status_badge.setMinimumHeight(24)
        verdict.body.addWidget(self.status_badge, 0)
        self.message_label = QLabel(
            "Choose a file and run a check to see the result."
        )
        self.message_label.setObjectName("Muted")
        self.message_label.setWordWrap(True)
        verdict.body.addWidget(self.message_label)
        right_layout.addWidget(verdict)

        details = Card(
            "Technical details",
            "What the file says about itself. Values marked as parsed are "
            "read from the header; they are only trustworthy once the file "
            "has been verified.",
        )
        self.detail_rows = {}
        for key, label in (
            ("format", "Format version"),
            ("dimensions", "Original size"),
            ("channels", "Colour channels"),
            ("iterations", "PBKDF2 iterations"),
            ("strip_rows", "Reserved strip"),
            ("size", "File size"),
            ("sha256", "SHA-256 of file"),
        ):
            row = InfoRow(label, "—", mono=key in ("sha256", "iterations"))
            self.detail_rows[key] = row
            details.body.addWidget(row)
        right_layout.addWidget(details)
        right_layout.addStretch(1)

        # The right column can be taller than the window (long digests, a
        # large preview) — scroll it instead of clipping it.
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        self.content.addWidget(splitter, 1)

        # -- action bar -------------------------------------------------------
        bar = QFrame()
        bar.setObjectName("StatusStrip")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(GAP_MD)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Muted")
        bar_layout.addWidget(self.status_label, 1)

        self.progress = QProgressBar()
        self.progress.setObjectName("verify_progress")
        self.progress.setToolTip("Progress of the running check")
        self.progress.setMaximumWidth(200)
        self.progress.setRange(0, 0)  # busy indicator while a check runs
        self.progress.setVisible(False)
        bar_layout.addWidget(self.progress)

        self.verify_btn = PrimaryButton("Verify")
        self.verify_btn.setObjectName("verify_run")
        self.verify_btn.setToolTip(
            "Check the selected file's format and, with a passphrase, its "
            "authentication tag"
        )
        bar_layout.addWidget(self.verify_btn)
        self.content.addWidget(bar)

    # -- results ------------------------------------------------------------
    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def reset(self) -> None:
        self.status_badge.set_status("Idle", "neutral")
        self.message_label.setText("Choose a file and run a check to see the result.")
        for row in self.detail_rows.values():
            row.set_value("—")

    def show_result(self, payload: dict) -> None:
        """Render a verification payload (see app.workers.VerifyWorker)."""
        status = payload.get("status", "unauthenticated")
        label, variant, _hint = _STATES.get(status, ("Unknown", "neutral", ""))
        self.status_badge.set_status(label, variant)
        self.message_label.setText(payload.get("message", ""))

        version = payload.get("version")
        self.detail_rows["format"].set_value(
            f"v{version} (OptiCipher v1)" if version else "—"
        )
        width = payload.get("width")
        height = payload.get("height")
        self.detail_rows["dimensions"].set_value(
            f"{width}×{height} px" if width and height else "—"
        )
        channels = payload.get("channels")
        self.detail_rows["channels"].set_value(
            f"{channels}" if channels else "—"
        )
        iterations = payload.get("iterations")
        self.detail_rows["iterations"].set_value(
            f"{iterations:,}" if iterations else "—"
        )
        strip = payload.get("strip_rows")
        self.detail_rows["strip_rows"].set_value(f"{strip} rows" if strip else "—")
        size = payload.get("size")
        if size:
            from ..imaging import human_size

            self.detail_rows["size"].set_value(
                f"{human_size(size)}  ({size:,} bytes)"
            )
        else:
            self.detail_rows["size"].set_value("—")
        self.detail_rows["sha256"].set_value(payload.get("sha256") or "—")
