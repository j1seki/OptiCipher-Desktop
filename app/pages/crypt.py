"""
app.pages.crypt
===============

The Encrypt and Decrypt screens.

Both are built from the same :class:`CryptPage` skeleton — source list,
secret, destination, action bar — because the two operations share their
shape. They differ in what they *claim*:

  * Encrypt reports what was produced (and where).
  * Decrypt reports the outcome **step by step** — the authentication
    result, whether the output was written, and whether the restoration was
    exact — so a partially failed run can never be presented as a green
    "done".

The pages own no logic: they collect input, and the window drives the
workers and writes the results back through :meth:`CryptPage.set_result`.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..theme import GAP_LG, GAP_MD, GAP_SM
from ..widgets import (
    Card,
    Field,
    FileList,
    PasswordField,
    PreviewPanel,
    PrimaryButton,
    SecondaryButton,
    StepRow,
)
from .base import BasePage

PASSPHRASE_TIP = (
    "The passphrase derives the encryption key (PBKDF2 + ChaCha20). "
    "There is NO recovery: without it the data cannot be decrypted — "
    "there is no key escrow and no back door."
)
CONFIRM_TIP = (
    "Type the same passphrase again — a typo here would make the "
    "encrypted file unrecoverable, so it must match exactly."
)
KDF_TIP = (
    "Key-derivation cost for NEW encryptions: the passphrase is "
    "stretched this many times with PBKDF2 before use. Higher = "
    "far slower to attack, a little slower to encrypt. Decryption "
    "reads the real cost from the image header and ignores this "
    "slider."
)
OUTPUT_TIP = (
    "Where results are written. Empty = next to the input file. "
    "Existing files are never overwritten — a numbered name "
    "(*_2.png) is used instead.\n"
    "SFTP: type sftp://user@server/remote/dir and every result is "
    "also uploaded there as a verified copy (the local file is kept). "
    "Passwords are asked once per session and never saved."
)
DECRYPT_KDF_HINT = (
    "The PBKDF2 cost is read from each file's own header — decryption "
    "always uses the value the file was encrypted with."
)


class CryptPage(BasePage):
    """Shared skeleton for the encrypt and decrypt screens."""

    mode = ""

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()

    # -- construction -------------------------------------------------------
    def _build(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        # -- left: the controls ---------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(GAP_MD)

        source_card = Card("Source images", "Add one image or a whole folder.")
        self.files = FileList()
        source_card.body.addWidget(self.files)
        left_layout.addWidget(source_card)

        secret_card = Card(
            "Passphrase",
            "The secret that protects the file. It is never stored anywhere.",
        )
        self.pass_field = PasswordField("Passphrase", PASSPHRASE_TIP)
        secret_card.body.addWidget(self.pass_field)
        self.pass_field.setToolTip(PASSPHRASE_TIP)
        self.pass_field.edit.setToolTip(PASSPHRASE_TIP)

        if self.mode == "encrypt":
            confirm_label = QLabel("Repeat passphrase")
            confirm_label.setObjectName("FieldLabel")
            confirm_label.setToolTip(CONFIRM_TIP)
            secret_card.body.addWidget(confirm_label)
            self.confirm_field = PasswordField("Repeat passphrase", CONFIRM_TIP)
            secret_card.body.addWidget(self.confirm_field)
            self.confirm_field.setToolTip(CONFIRM_TIP)
            self.confirm_field.edit.setToolTip(CONFIRM_TIP)
        left_layout.addWidget(secret_card)

        if self.mode == "encrypt":
            kdf_card = Card("Key derivation", KDF_TIP)
            kdf_row = QHBoxLayout()
            kdf_row.setSpacing(GAP_SM)
            self.kdf_slider = QSlider(Qt.Horizontal)
            self.kdf_slider.setRange(2, 40)  # x50k: 100k..2M
            self.kdf_slider.setValue(max(2, self._default_iterations() // 50_000))
            self.kdf_slider.setToolTip(KDF_TIP)
            self.kdf_slider.setAccessibleName("PBKDF2 iteration cost")
            self.kdf_label = QLabel()
            self.kdf_label.setObjectName("Muted")
            self.kdf_slider.valueChanged.connect(self._update_iter_label)
            self._update_iter_label(self.kdf_slider.value())
            kdf_row.addWidget(self.kdf_slider, 1)
            kdf_row.addWidget(self.kdf_label)
            kdf_card.body.addLayout(kdf_row)
            left_layout.addWidget(kdf_card)
        else:
            hint = QLabel(DECRYPT_KDF_HINT)
            hint.setObjectName("Faint")
            hint.setWordWrap(True)
            hint.setToolTip(DECRYPT_KDF_HINT)
            secret_card.body.addWidget(hint)

        dest_card = Card("Destination", "Where the results are written.")
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText(
            "Output folder or sftp://user@host/path (empty = next to input)"
        )
        self.out_edit.setToolTip(OUTPUT_TIP)
        self.out_edit.setAccessibleName("Output location")
        browse = QPushButton("Browse…")
        browse.setToolTip("Browse for an output folder")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._pick_out_dir)
        out_row = QHBoxLayout()
        out_row.setSpacing(GAP_SM)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(browse)
        dest_card.body.addLayout(out_row)
        self.browse_btn = browse
        left_layout.addWidget(dest_card)
        left_layout.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left)
        left_scroll.setMinimumWidth(360)
        splitter.addWidget(left_scroll)

        # -- right: preview + outcome ----------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(GAP_MD)

        self.preview = PreviewPanel()
        right_layout.addWidget(self.preview, 1)

        self.result_card = Card("Outcome", "What happened, step by step.")
        self.steps: dict = {}
        for name in self._step_names():
            row = StepRow(name)
            self.steps[name] = row
            self.result_card.body.addWidget(row)
        right_layout.addWidget(self.result_card)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)

        self.content.addWidget(splitter, 1)

        # -- action bar --------------------------------------------------------
        self._build_action_bar()

    def _step_names(self):
        return []

    def _default_iterations(self) -> int:
        from ..settings import AppSettings

        return AppSettings().iterations

    def _build_action_bar(self) -> None:
        bar = QFrame()
        bar.setObjectName("StatusStrip")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(GAP_MD)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Muted")
        bar_layout.addWidget(self.status_label, 1)

        self.progress = QProgressBar()
        self.progress.setObjectName(f"{self.mode}_progress")
        self.progress.setToolTip("Files processed in this batch")
        self.progress.setAccessibleName("Batch progress")
        self.progress.setFixedWidth(220)
        self.progress.setValue(0)
        bar_layout.addWidget(self.progress)

        self.cancel_btn = SecondaryButton("Cancel")
        self.cancel_btn.setObjectName(f"{self.mode}_cancel")
        self.cancel_btn.setToolTip(
            "Stops after the current file finishes — files already written "
            "remain valid and complete"
        )
        self.cancel_btn.setEnabled(False)
        bar_layout.addWidget(self.cancel_btn)

        self.start_btn = PrimaryButton("Encrypt" if self.mode == "encrypt" else "Decrypt")
        self.start_btn.setObjectName(f"{self.mode}_start")
        self.start_btn.setToolTip(
            "Process every file in the list with the passphrase above"
        )
        bar_layout.addWidget(self.start_btn)

        self.content.addWidget(bar)
        self.action_bar = bar

    # -- helpers ------------------------------------------------------------
    def _update_iter_label(self, value: int) -> None:
        self.kdf_label.setText(f"{value * 50_000:,} iterations")
        self.kdf_label.setMinimumWidth(140)

    def _pick_out_dir(self) -> None:
        from ..settings import AppSettings

        settings = AppSettings()
        directory = QFileDialog.getExistingDirectory(
            self, "Output folder", self.out_edit.text() or settings.last_dir
        )
        if directory:
            self.out_edit.setText(directory)
            settings.output_dir = directory

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_progress(self, percent: int) -> None:
        self.progress.setValue(percent)

    def set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.files.setEnabled(not running)
        self.out_edit.setEnabled(not running)
        self.pass_field.edit.setEnabled(not running)
        if hasattr(self, "confirm_field"):
            self.confirm_field.edit.setEnabled(not running)
        if hasattr(self, "kdf_slider"):
            self.kdf_slider.setEnabled(not running)

    def reset_steps(self) -> None:
        for row in self.steps.values():
            row.set_result("—", "neutral")

    def set_step(self, name: str, text: str, variant: str) -> None:
        row = self.steps.get(name)
        if row is not None:
            row.set_result(text, variant)


class EncryptPage(CryptPage):
    """Protect images with a passphrase."""

    mode = "encrypt"
    key = "encrypt"
    title = "Encrypt"
    subtitle = (
        "Protect images with a passphrase. The result is a self-contained PNG "
        "that carries everything needed to restore it — only your passphrase "
        "can open it."
    )

    def _step_names(self):
        return ["Files processed", "Result written", "Remote copy"]


class DecryptPage(CryptPage):
    """Restore an encrypted image."""

    mode = "decrypt"
    key = "decrypt"
    title = "Decrypt"
    subtitle = (
        "Restore an encrypted image. The passphrase is checked against the "
        "file's authentication tag before anything is written."
    )

    def _step_names(self):
        return [
            "Authentication (HMAC-SHA256)",
            "Output written",
            "Exact restoration",
        ]
