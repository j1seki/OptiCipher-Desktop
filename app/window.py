"""
app.window
==========

The OptiCipher Desktop main window.

Layout
------
    ┌────────────────────────────────────────────────────────────┐
    │ [ Encrypt | Decrypt | Analyze ]          device: GPU ▾ ⚙  │
    │ ┌───────────────────────┬────────────────────────────────┐ │
    │ │ mode-specific controls│  preview / results             │ │
    │ │  file list (batch)    │  (before | after)              │ │
    │ │  passphrase, options  │                                │ │
    │ │  progress, start/cancel                                │ │
    │ └───────────────────────┴────────────────────────────────┘ │
    │ status bar                                                 │
    └────────────────────────────────────────────────────────────┘

All heavy work happens in `app.workers` QThreads; this module is presentation
and wiring only. Compute settings chosen here are persisted via
`app.settings.AppSettings` and pushed into `opticipher.accel`, so the next job
runs on the selected device/threads/RAM budget.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from PIL import Image

from opticipher import __version__ as _lib_version
from opticipher import accel, load_image

from . import device as _device
from .charts import CHANNEL_LABELS, HistogramBars, ValueBar
from .sftp import is_sftp_output, parse_sftp_url
from .settings import AppSettings
from .workers import AnalyzeWorker, JobWorker, detect_opticipher_header

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"


# ---------------------------------------------------------------------------
# Image metadata + enlarge-on-click viewer.
# ---------------------------------------------------------------------------
def _human_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 ** 2:
        return f"{nbytes / 1024:.1f} KiB"
    if nbytes < 1024 ** 3:
        return f"{nbytes / 1024 ** 2:.1f} MiB"
    return f"{nbytes / 1024 ** 3:.2f} GiB"


def describe_image(path: str) -> str:
    """
    Human-readable metadata for the info panel: name, format, colour mode,
    dimensions, file size, and whether the file carries an OptiCipher
    ciphertext header (an unauthenticated peek — the HMAC is only verified
    during decryption).
    """
    lines = [os.path.basename(path)]
    try:
        size = _human_size(os.path.getsize(path))
        with Image.open(path) as im:
            width, height = im.size
            extra = f"{im.format or '?'} · {im.mode} · {width}×{height} · {size}"
            frames = getattr(im, "n_frames", 1)
            if frames > 1:
                extra += f" · {frames} frames"
        lines.append(extra)
    except Exception as exc:  # noqa: BLE001 - info panel, never fatal
        lines.append(f"(cannot read image info: {exc})")
        return "\n".join(lines)
    try:
        header = detect_opticipher_header(load_image(path))
    except Exception:  # noqa: BLE001 - unreadable pixels just mean "no header"
        header = None
    if header:
        lines.append(
            "OptiCipher v{version} header · original {width}×{height} "
            "{channels} ch · PBKDF2 {iterations:,} iters · strip "
            "{strip_rows} rows".format(**header)
        )
    else:
        lines.append("No OptiCipher header — plain image")
    return "\n".join(lines)


def _tipped_row(label_text: str, tip: str, widget: QWidget):
    """A form row whose label and widget both carry the same tooltip."""
    label = QLabel(label_text)
    label.setToolTip(tip)
    widget.setToolTip(tip)
    return label, widget


class ClickableLabel(QLabel):
    """QLabel that emits `clicked` on a left-click (enlarge-on-click previews)."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ImageViewer(QDialog):
    """Enlarge dialog: the image at its native size inside a scroll area."""

    def __init__(self, path: str, info_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        self.setAttribute(Qt.WA_DeleteOnClose)
        pix = QPixmap(path)
        image_label = QLabel()
        image_label.setPixmap(pix)
        image_label.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(image_label)
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        if info_text:
            info = QLabel(info_text)
            info.setWordWrap(True)
            info.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(info)
        layout.addWidget(scroll, 1)
        # Size the dialog to the screen, not the image: large images scroll,
        # small ones simply center. Esc ( QDialog default) closes.
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(
            max(420, min(pix.width() + 48, screen.width() - 100)),
            max(320, min(pix.height() + 90, screen.height() - 120)),
        )


# ---------------------------------------------------------------------------
# Building blocks.
# ---------------------------------------------------------------------------
class FileList(QWidget):
    """
    Batch file list with drag-and-drop and add/remove controls.

    Emits `selection_changed(path)` whenever the current item changes ("" when
    the selection is empty), so the window can show the file in the "before"
    preview the moment it is added — no job required to confirm you picked
    the right image.
    """

    selection_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.listw = QListWidget()
        self.listw.setSelectionMode(QListWidget.ExtendedSelection)
        self.listw.currentItemChanged.connect(self._on_current_changed)
        self.listw.setToolTip(
            "Images to process in one batch — add with the buttons below or "
            "drag & drop anywhere in the window. Clicking an item previews it."
        )
        add_btn = QPushButton("Add files…")
        folder_btn = QPushButton("Add folder…")
        clear_btn = QPushButton("Clear")
        add_btn.setToolTip("Pick one or more image files for the batch")
        folder_btn.setToolTip("Add every image inside a folder")
        clear_btn.setToolTip(
            "Remove every file from the list (does not delete anything on disk)"
        )
        add_btn.clicked.connect(self._add_dialog)
        folder_btn.clicked.connect(self._add_folder)
        clear_btn.clicked.connect(self.listw.clear)
        row = QHBoxLayout()
        row.addWidget(add_btn)
        row.addWidget(folder_btn)
        row.addStretch(1)
        row.addWidget(clear_btn)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.listw)

    def paths(self) -> List[str]:
        return [
            self.listw.item(i).data(Qt.UserRole)
            for i in range(self.listw.count())
        ]

    def current_path(self) -> str:
        item = self.listw.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def add_paths(self, paths: List[str]) -> None:
        existing = set(self.paths())
        first_new = None
        for path in paths:
            if path not in existing:
                item = QListWidgetItem(os.path.basename(path))
                item.setToolTip(path)
                item.setData(Qt.UserRole, path)
                self.listw.addItem(item)
                if first_new is None:
                    first_new = item
        # Select the newly added file so the preview + info panel update
        # immediately, before any job is started.
        if first_new is not None:
            self.listw.setCurrentItem(first_new)

    def _on_current_changed(self, current, _previous) -> None:
        self.selection_changed.emit(
            current.data(Qt.UserRole) if current is not None else ""
        )

    def _add_dialog(self) -> None:
        settings = AppSettings()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose images", settings.last_dir, _IMAGE_FILTER
        )
        if paths:
            settings.last_dir = os.path.dirname(paths[0])
            self.add_paths(paths)

    def _add_folder(self) -> None:
        settings = AppSettings()
        directory = QFileDialog.getExistingDirectory(
            self, "Choose folder", settings.last_dir
        )
        if not directory:
            return
        found = [
            os.path.join(directory, name)
            for name in sorted(os.listdir(directory))
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif"))
        ]
        self.add_paths(found)


class SettingsDialog(QDialog):
    """Compute + crypto settings; on accept they persist and apply live."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — OptiCipher Desktop")
        self.settings = AppSettings()

        form = QFormLayout()

        self.device_combo = QComboBox()
        self._fill_devices()
        form.addRow(
            *_tipped_row(
                "Compute device",
                "Where the heavy work runs. Auto does a one-time speed test "
                "on this machine and picks the faster of GPU and CPU. GPU "
                "uses WebGPU — Metal on macOS, Vulkan on Linux, DirectX 12 "
                "on Windows — and falls back to CPU when no adapter exists.",
                self.device_combo,
            )
        )

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 256)
        self.threads_spin.setValue(self.settings.threads)
        self.threads_spin.setSpecialValueText("Auto (all cores)")
        form.addRow(
            *_tipped_row(
                "CPU threads",
                "Worker threads for the CPU backend. Auto uses every core. "
                "The GPU backend ignores this setting.",
                self.threads_spin,
            )
        )

        self.ram_spin = QSpinBox()
        self.ram_spin.setRange(16, 65536)
        self.ram_spin.setSingleStep(64)
        self.ram_spin.setSuffix(" MB")
        self.ram_spin.setValue(self.settings.ram_budget_mb)
        form.addRow(
            *_tipped_row(
                "RAM budget",
                "Upper bound on the working memory a single image may use. "
                "Images that would exceed it still process, but the backend "
                "may fall back to a slower path — raise this if very large "
                "images fail or crawl.",
                self.ram_spin,
            )
        )

        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(10_000, 2_000_000)
        self.iter_spin.setSingleStep(50_000)
        self.iter_spin.setValue(self.settings.iterations)
        form.addRow(
            *_tipped_row(
                "PBKDF2 iterations",
                "Key-derivation cost stored in every NEW ciphertext: how "
                "many times the passphrase is stretched before use. Higher "
                "makes guessing the passphrase far slower and encryption a "
                "little slower. Decryption always reads the stored value "
                "from the image header — this setting never affects it.",
                self.iter_spin,
            )
        )

        info = QGroupBox("This machine")
        info_form = QFormLayout(info)
        info_form.addRow("CPU cores", QLabel(str(_device.cpu_count())))
        ram = _device.total_ram_mb()
        info_form.addRow(
            "System RAM", QLabel(f"{ram / 1024:.1f} GiB" if ram else "unknown")
        )
        info_form.addRow("Platform", QLabel(_device.platform_summary()))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(info)
        layout.addWidget(buttons)

    def _fill_devices(self) -> None:
        self.device_combo.clear()
        rows = _device.compute_backends()
        gpu_rows = [r for r in rows if r.get("name") == "gpu" and r.get("available")]
        cpu_rows = [r for r in rows if r.get("name") == "cpu"]
        self.device_combo.addItem("Auto (prefer GPU)", "auto")
        for row in gpu_rows:
            self.device_combo.addItem(f"GPU — {row.get('detail', '')}", "gpu")
        for row in cpu_rows:
            self.device_combo.addItem(
                f"CPU — {row.get('detail', 'processor')}", "cpu"
            )
        # Grey-out note when no GPU is present.
        if not gpu_rows:
            self.device_combo.setItemData(
                1, "No usable GPU adapter detected", Qt.ToolTipRole
            )
        current = self.settings.device
        index = self.device_combo.findData(current)
        self.device_combo.setCurrentIndex(max(0, index))

    def accept(self) -> None:  # noqa: N802 (Qt naming)
        self.settings.device = self.device_combo.currentData()
        self.settings.threads = self.threads_spin.value()
        self.settings.ram_budget_mb = self.ram_spin.value()
        self.settings.iterations = self.iter_spin.value()
        self.settings.apply_to_accel()
        super().accept()


# ---------------------------------------------------------------------------
# SFTP credentials — session-memory only, never persisted.
# ---------------------------------------------------------------------------
class SftpCredentialsDialog(QDialog):
    """
    Ask for the credentials of an ``sftp://`` output location.

    The values exist only in this dialog and the caller's memory: they are
    never written to QSettings, never logged, and never allowed inside the
    URL itself (parse_sftp_url refuses embedded passwords).
    """

    def __init__(self, target, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"SFTP login — {target.host}")
        form = QFormLayout(self)
        dest = QLabel(target.describe())
        dest.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Destination", dest)

        self.user_edit = QLineEdit(target.user)
        self.user_edit.setPlaceholderText("SSH user (empty = current user)")
        self.user_edit.setToolTip(
            "Account on the SFTP server; leave empty to use your login name"
        )
        form.addRow("User", self.user_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Password (session only)")
        self.password_edit.setToolTip(
            "Held in memory for this run of OptiCipher only — never saved to "
            "settings, disk or logs"
        )
        form.addRow("Password", self.password_edit)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText(
            "Optional: path to a private key (used instead of a password)"
        )
        key_browse = QPushButton("…")
        key_browse.setFixedWidth(32)
        key_browse.setToolTip("Browse for an SSH private key file")
        key_browse.clicked.connect(self._pick_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(key_browse)
        form.addRow("Key file", key_row)

        note = QLabel(
            "Kept in memory for this session only — never written to disk."
        )
        note.setStyleSheet("color:#888;")
        note.setWordWrap(True)
        form.addRow("", note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _pick_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "SSH private key", os.path.expanduser("~")
        )
        if path:
            self.key_edit.setText(path)

    def credentials(self) -> dict:
        """The entered credentials (empty fields become None)."""
        return {
            "user": self.user_edit.text().strip(),
            "password": self.password_edit.text() or None,
            "key_file": self.key_edit.text().strip() or None,
        }


# ---------------------------------------------------------------------------
# Main window.
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"OptiCipher Desktop { _lib_version }")
        self.resize(1180, 760)
        self.setAcceptDrops(True)

        self.settings = AppSettings()
        self.settings.apply_to_accel()

        self._job: Optional[JobWorker] = None
        self._analyze: Optional[AnalyzeWorker] = None
        self._last_output_path: Optional[str] = None
        # SFTP credentials for THIS RUN ONLY (never QSettings — see
        # SftpCredentialsDialog). Keyed by (host, port, user).
        self._sftp_sessions: dict = {}

        self._build_ui()
        self._refresh_device_bar()
        self.statusBar().showMessage("Ready — drop images anywhere to add them")

    # -- construction -------------------------------------------------------
    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.encrypt_tab = self._build_crypt_tab("encrypt")
        self.decrypt_tab = self._build_crypt_tab("decrypt")
        self.analyze_tab = self._build_analyze_tab()
        self.tabs.addTab(self.encrypt_tab, "Encrypt")
        self.tabs.addTab(self.decrypt_tab, "Decrypt")
        self.tabs.addTab(self.analyze_tab, "Analyze")

        # Any file-list selection previews the file immediately — before any
        # job runs — and refreshes the info panel.
        for files in list(self.file_lists.values()) + [self.analyze_files]:
            files.selection_changed.connect(self._on_source_selected)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tabs)
        self.preview_before = self._preview_label("before")
        self.preview_after = self._preview_label("after")
        self.preview_before._label.clicked.connect(  # type: ignore[attr-defined]
            lambda: self._enlarge("before")
        )
        self.preview_after._label.clicked.connect(  # type: ignore[attr-defined]
            lambda: self._enlarge("after")
        )
        preview = QWidget()
        pv = QVBoxLayout(preview)
        ph = QHBoxLayout()
        ph.addWidget(self.preview_before, 1)
        ph.addWidget(self.preview_after, 1)
        pv.addLayout(ph, 1)
        caption = QLabel(
            "Selected file shows here immediately — click a preview to enlarge"
        )
        caption.setStyleSheet("color:#888;")
        pv.addWidget(caption)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setStyleSheet("color:#9aa0ae;")
        pv.addWidget(self.info_label)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(splitter, 1)
        self.device_label = QLabel()
        self.device_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.device_label.setToolTip(
            "Acceleration backend in use (GPU via WebGPU, or CPU fallback) "
            "and its thread settings — change it in Settings"
        )
        layout.addWidget(self.device_label)
        self.setCentralWidget(central)

        # Menu bar.
        file_menu = self.menuBar().addMenu("&File")
        open_act = QAction("Add images…", self)
        open_act.triggered.connect(self._add_images_dialog)
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        settings_menu = self.menuBar().addMenu("&Settings")
        conf_act = QAction("Compute & crypto…", self)
        conf_act.triggered.connect(self._open_settings)
        settings_menu.addAction(conf_act)

        help_menu = self.menuBar().addMenu("&Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._about)
        help_menu.addAction(about_act)

        self.setStatusBar(QStatusBar())

    def _preview_label(self, which: str) -> QGroupBox:
        box = QGroupBox("original" if which == "before" else "result")
        label = ClickableLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(240, 200)
        label.setStyleSheet("background:#181a20; color:#888;")
        label.setText("(empty)")
        label.setCursor(Qt.PointingHandCursor)
        label.setToolTip("Click to enlarge")
        layout = QVBoxLayout(box)
        layout.addWidget(label)
        box._label = label  # type: ignore[attr-defined]
        box._which = which  # type: ignore[attr-defined]
        box._path = None  # type: ignore[attr-defined]
        box._pixmap = None  # type: ignore[attr-defined]
        return box

    def _build_crypt_tab(self, mode: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # NB: read back the attribute we actually store on — a stale name here
        # makes the second tab's construction drop the first tab's list.
        self.file_lists = getattr(self, "file_lists", {})
        files = FileList()
        self.file_lists[mode] = files
        layout.addWidget(files, 1)

        pass_row = QHBoxLayout()
        pass_edit = QLineEdit()
        pass_edit.setEchoMode(QLineEdit.Password)
        pass_edit.setPlaceholderText("Passphrase")
        pass_tip = (
            "The passphrase derives the encryption key (PBKDF2 + ChaCha20). "
            "There is NO recovery: without it the data cannot be decrypted — "
            "there is no key escrow and no back door."
        )
        pass_edit.setToolTip(pass_tip)
        pass_label = QLabel("Passphrase")
        pass_label.setToolTip(pass_tip)
        pass_row.addWidget(pass_label)
        pass_row.addWidget(pass_edit, 1)
        if mode == "encrypt":
            confirm_edit = QLineEdit()
            confirm_edit.setEchoMode(QLineEdit.Password)
            confirm_edit.setPlaceholderText("Repeat passphrase")
            confirm_edit.setToolTip(
                "Type the same passphrase again — a typo here would make the "
                "encrypted file unrecoverable, so it must match exactly."
            )
            pass_row.addWidget(confirm_edit)
            setattr(self, f"_{mode}_confirm", confirm_edit)
        setattr(self, f"_{mode}_pass", pass_edit)
        layout.addLayout(pass_row)

        options = QHBoxLayout()
        if mode == "encrypt":
            # NB: this must be encrypt-tab-local. Building a slider/label pair
            # for both tabs into the SAME attributes made the decrypt tab's
            # hidden slider silently replace the visible encrypt one — moving
            # it updated nothing and the chosen cost never reached the job.
            self._enc_iter_slider = QSlider(Qt.Horizontal)
            self._enc_iter_slider.setRange(2, 40)  # x50k: 100k..2M
            self._enc_iter_slider.setValue(
                max(2, self.settings.iterations // 50_000)
            )
            kdf_tip = (
                "Key-derivation cost for NEW encryptions: the passphrase is "
                "stretched this many times with PBKDF2 before use. Higher = "
                "far slower to attack, a little slower to encrypt. Decryption "
                "reads the real cost from the image header and ignores this "
                "slider."
            )
            self._enc_iter_slider.setToolTip(kdf_tip)
            self._enc_iter_label = QLabel()
            self._enc_iter_slider.valueChanged.connect(
                lambda value: self._update_iter_label(
                    self._enc_iter_label, value
                )
            )
            self._update_iter_label(
                self._enc_iter_label, self._enc_iter_slider.value()
            )
            kdf_caption = QLabel("KDF cost")
            kdf_caption.setToolTip(kdf_tip)
            options.addWidget(kdf_caption)
            options.addWidget(self._enc_iter_slider, 1)
            options.addWidget(self._enc_iter_label)
        else:
            hint = QLabel("Iterations are read from the image header automatically")
            hint.setStyleSheet("color:#888;")
            hint.setToolTip(
                "Each encrypted image records its own PBKDF2 cost in the "
                "authenticated header — decryption always uses the value the "
                "file was encrypted with, whatever the Encrypt tab says."
            )
            options.addWidget(hint)
            options.addStretch(1)
        layout.addLayout(options)

        out_row = QHBoxLayout()
        out_edit = QLineEdit(self.settings.output_dir)
        out_edit.setPlaceholderText(
            "Output folder or sftp://user@host/path (empty = next to input)"
        )
        out_tip = (
            "Where results are written. Empty = next to the input file. "
            "Existing files are never overwritten — a numbered name "
            "(*_2.png) is used instead.\n"
            "SFTP: type sftp://user@server/remote/dir and every result is "
            "also uploaded there as a verified copy (the local file is kept). "
            "Passwords are asked once per session and never saved."
        )
        out_edit.setToolTip(out_tip)
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.setToolTip("Browse for an output folder")
        browse.clicked.connect(lambda: self._pick_out_dir(out_edit))
        out_label = QLabel("Output")
        out_label.setToolTip(out_tip)
        out_row.addWidget(out_label)
        out_row.addWidget(out_edit, 1)
        out_row.addWidget(browse)
        setattr(self, f"_{mode}_out", out_edit)
        layout.addLayout(out_row)

        actions = QHBoxLayout()
        start_btn = QPushButton("Start" if mode == "encrypt" else "Decrypt")
        start_btn.setObjectName(f"{mode}_start")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName(f"{mode}_cancel")
        cancel_btn.setEnabled(False)
        start_btn.setToolTip(
            "Process every file in the list with the passphrase above"
        )
        cancel_btn.setToolTip(
            "Stops after the current file finishes — files already written "
            "remain valid and complete"
        )
        start_btn.clicked.connect(lambda: self._start_job(mode))
        cancel_btn.clicked.connect(lambda: self._cancel_job(mode))
        progress = QProgressBar()
        progress.setObjectName(f"{mode}_progress")
        progress.setToolTip("Files processed in this batch")
        actions.addWidget(start_btn)
        actions.addWidget(cancel_btn)
        actions.addWidget(progress, 1)
        layout.addLayout(actions)
        return widget

    def _build_analyze_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        files = FileList()
        self.analyze_files = files
        layout.addWidget(files, 1)
        hint = QLabel(
            "Select 1 image for entropy/correlation/histogram — or pair an "
            "image with its OptiCipher ciphertext (or two same-size images) "
            "for NPCR/UACI."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        hint.setToolTip(hint.text())
        layout.addWidget(hint)

        run_btn = QPushButton("Run analysis")
        run_btn.setObjectName("analyze_run")
        run_btn.setToolTip(
            "Compute entropy, adjacent-pixel correlation and histograms for "
            "the selection (1 image) — plus NPCR/UACI for a ciphertext pair"
        )
        run_btn.clicked.connect(self._start_analyze)
        layout.addWidget(run_btn)

        results = QWidget()
        self.results_layout = QVBoxLayout(results)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.header_label = QLabel("")
        self.header_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.results_layout.addWidget(self.header_label)
        self.metric_bars: dict = {}
        for name, ideal in (
            ("Entropy (mean)", (7.9, 8.0)),
            ("NPCR %", (99.5, 99.7)),
            ("UACI %", (33.3, 33.5)),
        ):
            bar = ValueBar(name, maximum=100.0 if "%" in name else 8.0, ideal=ideal)
            self.metric_bars[name] = bar
            self.results_layout.addWidget(bar)
        self.metric_bars["Entropy (mean)"].setToolTip(
            "Shannon entropy in bits/byte — ideal ciphertext sits at 8.0 "
            "(uniform noise); the green band marks the target range"
        )
        self.metric_bars["NPCR %"].setToolTip(
            "Number of Pixel Change Rate between two encryptions — ideal "
            "~99.6%; measures how completely a one-pixel change spreads"
        )
        self.metric_bars["UACI %"].setToolTip(
            "Unified Average Changing Intensity between two encryptions — "
            "ideal ~33.5%"
        )
        self.corr_table = QTableWidget(0, 3)
        self.corr_table.setHorizontalHeaderLabels(
            ["horizontal", "vertical", "diagonal"]
        )
        self.corr_table.verticalHeader().setVisible(True)
        corr_label = QLabel("Adjacent-pixel correlation")
        corr_label.setToolTip(
            "Correlation between neighbouring pixels — ideal ciphertext is "
            "near 0 in every direction (no structure left)"
        )
        self.results_layout.addWidget(corr_label)
        self.results_layout.addWidget(self.corr_table)
        hist_row = QHBoxLayout()
        hist_label = QLabel("Histogram channel")
        hist_label.setToolTip(
            "Which colour channel the histogram below displays"
        )
        hist_row.addWidget(hist_label)
        self.hist_channel = QComboBox()
        self.hist_channel.setToolTip(
            "Pick a colour channel — bar colours follow it (red / green / "
            "blue / amber)"
        )
        self.hist_channel.currentIndexChanged.connect(self._update_hist)
        hist_row.addWidget(self.hist_channel)
        hist_row.addStretch(1)
        self.results_layout.addLayout(hist_row)
        self.hist_widget = HistogramBars()
        self.hist_widget.setToolTip(
            "Distribution of byte values (256 bins, sqrt height) — a flat "
            "histogram indicates good diffusion"
        )
        self.results_layout.addWidget(self.hist_widget)
        self._hist_data: dict = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(results)
        layout.addWidget(scroll, 2)
        return widget

    # -- drag & drop --------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if os.path.isfile(url.toLocalFile())
        ]
        if paths:
            self._active_file_list().add_paths(paths)
            self.statusBar().showMessage(f"Added {len(paths)} file(s)")

    # -- helpers ------------------------------------------------------------
    def _active_file_list(self) -> FileList:
        mode = self.tabs.tabText(self.tabs.currentIndex()).lower()
        if mode == "analyze":
            return self.analyze_files
        return self.file_lists.get(mode, self.analyze_files)

    def _add_images_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add images", self.settings.last_dir, _IMAGE_FILTER
        )
        if paths:
            self.settings.last_dir = os.path.dirname(paths[0])
            self._active_file_list().add_paths(paths)

    def _pick_out_dir(self, edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Output folder", edit.text() or self.settings.last_dir
        )
        if directory:
            edit.setText(directory)
            self.settings.output_dir = directory

    def _update_iter_label(self, label: QLabel, slider_value: int) -> None:
        label.setText(f"{slider_value * 50_000:,} iterations")
        label.setMinimumWidth(140)

    @property
    def iter_slider(self) -> QSlider:
        """The Encrypt tab's KDF-cost slider (kept for scripts and tests)."""
        return self._enc_iter_slider

    @property
    def iter_label(self) -> QLabel:
        """The Encrypt tab's KDF-cost value label."""
        return self._enc_iter_label

    def _open_settings(self) -> None:
        if SettingsDialog(self).exec() == QDialog.Accepted:
            self._refresh_device_bar()
            self.statusBar().showMessage("Settings applied", 4000)

    def _refresh_device_bar(self) -> None:
        cfg = accel.get_config()
        backend = accel.get_backend()
        info = backend.info()
        detail = info.get("detail", backend.name)
        calib = info.get("calibration", "")
        ram = _device.total_ram_mb()
        self.device_label.setText(
            f"Device: {detail}   ·   threads: {cfg['resolved_threads']}   ·   "
            f"RAM budget: {cfg['resolved_ram_mb']} MiB   ·   "
            f"system RAM: {ram / 1024:.1f} GiB"
            + (f"   ·   {calib}" if calib else "")
        )
        self.device_label.setStyleSheet("color:#9aa0ae; padding:2px;")

    def _set_preview(self, which: str, path: str) -> None:
        box = self.preview_before if which == "before" else self.preview_after
        label = box._label  # type: ignore[attr-defined]
        pix = QPixmap(path)
        if pix.isNull():
            label.setText("(cannot load preview)")
            return
        box._pixmap = pix  # type: ignore[attr-defined]
        box._path = path  # type: ignore[attr-defined]
        label.setPixmap(
            pix.scaled(label.size() * 0.98, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        box.setTitle(f"{which} — {os.path.basename(path)}")
        if which == "before":
            self.info_label.setText(describe_image(path))

    def _clear_preview(self, which: str) -> None:
        box = self.preview_before if which == "before" else self.preview_after
        box._label.setText("(empty)")  # type: ignore[attr-defined]
        box._label.setPixmap(QPixmap())  # type: ignore[attr-defined]
        box._pixmap = None  # type: ignore[attr-defined]
        box._path = None  # type: ignore[attr-defined]
        box.setTitle("original" if which == "before" else "result")
        if which == "before":
            self.info_label.setText("")

    def _on_source_selected(self, path: str) -> None:
        """Show the selected source immediately — before any job runs."""
        if path:
            self._set_preview("before", path)
        else:
            self._clear_preview("before")

    def _enlarge(self, which: str) -> None:
        """Open the enlarge viewer for a preview (click-to-enlarge)."""
        box = self.preview_before if which == "before" else self.preview_after
        path = getattr(box, "_path", None)
        if not path:
            return
        viewer = ImageViewer(path, describe_image(path), self)
        viewer.setWindowTitle(f"{which} — {os.path.basename(path)}")
        viewer.exec()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Re-fit stored pixmaps when the window resizes.
        for box in (
            getattr(self, "preview_before", None),
            getattr(self, "preview_after", None),
        ):
            if box is None:
                continue
            pix = getattr(box, "_pixmap", None)
            if pix is not None and not pix.isNull():
                box._label.setPixmap(  # type: ignore[attr-defined]
                    pix.scaled(
                        box._label.size() * 0.98,  # type: ignore[attr-defined]
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )

    # -- encrypt / decrypt jobs ---------------------------------------------
    def _start_job(self, mode: str) -> None:
        if self._job is not None and self._job.isRunning():
            return
        files = self.file_lists[mode].paths()
        if not files:
            QMessageBox.information(self, "OptiCipher", "Add at least one image first.")
            return
        passphrase = getattr(self, f"_{mode}_pass").text()
        if not passphrase:
            QMessageBox.warning(self, "OptiCipher", "Enter a passphrase.")
            return
        if mode == "encrypt":
            confirm = getattr(self, f"_{mode}_confirm").text()
            if passphrase != confirm:
                QMessageBox.warning(
                    self, "OptiCipher", "Passphrases do not match."
                )
                return
            iterations = self._enc_iter_slider.value() * 50_000
            self.settings.iterations = iterations
        else:
            iterations = self.settings.iterations  # unused for decrypt
        out_dir = getattr(self, f"_{mode}_out").text().strip()
        self.settings.output_dir = out_dir

        # sftp:// destinations: validate the URL before anything starts, then
        # collect credentials once per (host, port, user) for this session.
        sftp_cfg = None
        if is_sftp_output(out_dir):
            try:
                target = parse_sftp_url(out_dir)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid SFTP location", str(exc))
                return
            sftp_cfg = self._sftp_credentials(target)
            if sftp_cfg is None:
                return  # login cancelled — start no job

        self._set_preview("before", files[0])
        self.preview_after._label.setText("(pending)")  # type: ignore[attr-defined]

        self._job = JobWorker(
            mode, files, passphrase, iterations, out_dir, sftp=sftp_cfg
        )
        self._job_failures: list = []  # (path, reason) for the batch summary
        self._job.progress.connect(
            lambda pct, msg, m=mode: self._on_progress(m, pct, msg)
        )
        self._job.file_done.connect(self._on_file_done)
        self._job.all_done.connect(lambda ok, bad, m=mode: self._on_all_done(m, ok, bad))
        self._job.start()

        for suffix in ("start", "cancel"):
            btn = self.tabs.findChild(QPushButton, f"{mode}_{suffix}")
            if btn:
                btn.setEnabled(suffix == "cancel")
        self.statusBar().showMessage(f"{mode.capitalize()}ing…")

    def _cancel_job(self, mode: str) -> None:
        if self._job is not None:
            self._job.cancel()
            self.statusBar().showMessage("Cancelling after the current file…", 5000)

    def _on_progress(self, mode: str, pct: int, message: str) -> None:
        bar = self.tabs.findChild(QProgressBar, f"{mode}_progress")
        if bar:
            bar.setValue(pct)
        self.statusBar().showMessage(message)

    def _sftp_credentials(self, target) -> Optional[dict]:
        """Credentials for this target — cached in memory for the session."""
        session_key = (target.host, target.port, target.user)
        cached = self._sftp_sessions.get(session_key)
        if cached:
            return dict(cached)
        dialog = SftpCredentialsDialog(target, self)
        if dialog.exec() != QDialog.Accepted:
            return None
        creds = dialog.credentials()
        # Cache under host/port + the user that will actually be used; a user
        # typed here differs from the URL's, the next run re-asks (deliberate:
        # never silently authenticate as a different account than the URL).
        cache_key = (
            target.host,
            target.port,
            creds["user"] or target.user,
        )
        self._sftp_sessions[cache_key] = dict(creds)
        return dict(creds)

    def _on_file_done(self, path: str, status: str) -> None:
        if status.startswith("ok: "):
            # Payload may be "<local> → uploaded sftp://…" — preview/status
            # use the LOCAL file (it always exists; mirror upload never
            # deletes it).
            payload = status[4:]
            out_path = payload.split(" → ")[0]
            self._last_output_path = out_path
            self._set_preview("after", out_path)
            self.statusBar().showMessage(f"Saved {payload}", 8000)
        else:
            self.statusBar().showMessage(f"{os.path.basename(path)}: {status}", 10000)
            if "error" in status:
                # Collect instead of popping one modal per file: a batch of
                # failures must not bury the user under dialogs. The full
                # summary lands once, at all_done.
                self._job_failures.append((path, status))

    def _on_all_done(self, mode: str, ok: int, bad: int) -> None:
        for suffix in ("start", "cancel"):
            btn = self.tabs.findChild(QPushButton, f"{mode}_{suffix}")
            if btn:
                btn.setEnabled(suffix == "start")
        bar = self.tabs.findChild(QProgressBar, f"{mode}_progress")
        if bar:
            bar.setValue(100)
        self.statusBar().showMessage(
            f"Finished: {ok} succeeded, {bad} failed/cancelled", 8000
        )
        self._refresh_device_bar()

        failures = getattr(self, "_job_failures", [])
        if failures:
            shown = "\n".join(
                f"• {os.path.basename(p)} — {reason}"
                for p, reason in failures[:10]
            )
            more = (
                f"\n…and {len(failures) - 10} more" if len(failures) > 10 else ""
            )
            QMessageBox.warning(
                self,
                "Job finished with errors",
                f"{ok} succeeded, {len(failures)} failed:\n\n{shown}{more}",
            )
            self._job_failures = []

    # -- analyze ------------------------------------------------------------
    def _start_analyze(self) -> None:
        if self._analyze is not None and self._analyze.isRunning():
            return
        files = self.analyze_files.paths()
        if not files:
            QMessageBox.information(self, "OptiCipher", "Add at least one image first.")
            return
        self.statusBar().showMessage("Analyzing…")
        self._analyze = AnalyzeWorker(files)
        self._analyze.result.connect(self._on_analyze_result)
        self._analyze.failed.connect(
            lambda msg: QMessageBox.warning(self, "Analyze error", msg)
        )
        self._analyze.start()

    def _on_analyze_result(self, data: dict) -> None:
        header = data.get("header")
        if header:
            self.header_label.setText(
                "OptiCipher v{version} header · original {width}×{height} "
                "{channels}ch · PBKDF2 {iterations:,} iters · strip {strip_rows} rows".format(
                    **header
                )
            )
        else:
            self.header_label.setText(
                "No OptiCipher header found (plain image, or not a v1 ciphertext)"
            )
        entropy = data["entropy"]
        self.metric_bars["Entropy (mean)"].set_value(entropy.get("mean"))
        self.metric_bars["NPCR %"].set_value(data.get("npcr"))
        self.metric_bars["UACI %"].set_value(data.get("uaci"))

        corr = data["correlation"]
        self.corr_table.setRowCount(len(corr))
        for row, (chan, vals) in enumerate(corr.items()):
            item = QTableWidgetItem(chan)
            self.corr_table.setItem(row, 0, item)  # placeholder, replaced below
            for col, key in enumerate(("horizontal", "vertical", "diagonal")):
                self.corr_table.setItem(
                    row, col, QTableWidgetItem(f"{vals[key]:.4f}")
                )
            self.corr_table.setVerticalHeaderItem(row, QTableWidgetItem(chan))

        self._hist_data = data["histograms"]
        self.hist_channel.blockSignals(True)
        self.hist_channel.clear()
        for key in self._hist_data:
            self.hist_channel.addItem(CHANNEL_LABELS.get(key, key), key)
        self.hist_channel.blockSignals(False)
        self._update_hist()
        self.statusBar().showMessage(
            f"Analysis complete on backend: {data['backend']}", 8000
        )

    def _update_hist(self) -> None:
        key = self.hist_channel.currentData() or self.hist_channel.currentText()
        if key and key in self._hist_data:
            self.hist_widget.set_counts(self._hist_data[key], key=key)

    # -- about --------------------------------------------------------------
    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About OptiCipher Desktop",
            f"<b>OptiCipher Desktop {_lib_version}</b><br><br>"
            "Optical (perceptual) image encryption — a desktop app over the "
            "OptiCipher library by bio-colab (MIT License).<br><br>"
            "GPU acceleration via WebGPU (Metal / Vulkan / DX12) with CPU "
            "fallback. Output files are bit-compatible with the original "
            "OptiCipher CLI.<br><br>"
            "Research/educational tool — read the threat model before relying "
            "on it for anything that truly matters.",
        )
