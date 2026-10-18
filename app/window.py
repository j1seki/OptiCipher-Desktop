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

from PySide6.QtCore import Qt, QSettings, QTimer
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

from opticipher import __version__ as _lib_version
from opticipher import accel

from . import device as _device
from .charts import HistogramBars, ValueBar
from .settings import AppSettings
from .workers import AnalyzeWorker, JobWorker

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"


# ---------------------------------------------------------------------------
# Building blocks.
# ---------------------------------------------------------------------------
class FileList(QWidget):
    """Batch file list with drag-and-drop and add/remove controls."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.listw = QListWidget()
        self.listw.setSelectionMode(QListWidget.ExtendedSelection)
        add_btn = QPushButton("Add files…")
        folder_btn = QPushButton("Add folder…")
        clear_btn = QPushButton("Clear")
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

    def add_paths(self, paths: List[str]) -> None:
        existing = set(self.paths())
        for path in paths:
            if path not in existing:
                item = QListWidgetItem(os.path.basename(path))
                item.setToolTip(path)
                item.setData(Qt.UserRole, path)
                self.listw.addItem(item)

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
        form.addRow("Compute device", self.device_combo)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 256)
        self.threads_spin.setValue(self.settings.threads)
        self.threads_spin.setSpecialValueText("Auto (all cores)")
        form.addRow("CPU threads", self.threads_spin)

        self.ram_spin = QSpinBox()
        self.ram_spin.setRange(16, 65536)
        self.ram_spin.setSingleStep(64)
        self.ram_spin.setSuffix(" MB")
        self.ram_spin.setValue(self.settings.ram_budget_mb)
        form.addRow("RAM budget", self.ram_spin)

        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(10_000, 2_000_000)
        self.iter_spin.setSingleStep(50_000)
        self.iter_spin.setValue(self.settings.iterations)
        form.addRow("PBKDF2 iterations", self.iter_spin)

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

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tabs)
        self.preview_before = self._preview_label("original")
        self.preview_after = self._preview_label("result")
        preview = QWidget()
        pv = QVBoxLayout(preview)
        ph = QHBoxLayout()
        ph.addWidget(self.preview_before, 1)
        ph.addWidget(self.preview_after, 1)
        pv.addLayout(ph, 1)
        pv.addWidget(QLabel("Preview updates when a job finishes"))
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(splitter, 1)
        self.device_label = QLabel()
        self.device_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
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

    def _preview_label(self, caption: str) -> QGroupBox:
        box = QGroupBox(caption)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(240, 200)
        label.setStyleSheet("background:#181a20; color:#888;")
        label.setText("(empty)")
        layout = QVBoxLayout(box)
        layout.addWidget(label)
        box._label = label  # type: ignore[attr-defined]
        return box

    def _build_crypt_tab(self, mode: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.file_lists = getattr(self, "_file_lists", {})
        files = FileList()
        self.file_lists[mode] = files
        layout.addWidget(files, 1)

        pass_row = QHBoxLayout()
        pass_edit = QLineEdit()
        pass_edit.setEchoMode(QLineEdit.Password)
        pass_edit.setPlaceholderText("Passphrase")
        pass_row.addWidget(QLabel("Passphrase"))
        pass_row.addWidget(pass_edit, 1)
        if mode == "encrypt":
            confirm_edit = QLineEdit()
            confirm_edit.setEchoMode(QLineEdit.Password)
            confirm_edit.setPlaceholderText("Repeat passphrase")
            pass_row.addWidget(confirm_edit)
            setattr(self, f"_{mode}_confirm", confirm_edit)
        setattr(self, f"_{mode}_pass", pass_edit)
        layout.addLayout(pass_row)

        options = QHBoxLayout()
        self.iter_slider = QSlider(Qt.Horizontal)
        self.iter_slider.setRange(2, 40)  # x50k: 100k..2M
        self.iter_slider.setValue(max(2, self.settings.iterations // 50_000))
        self.iter_label = QLabel()
        self._update_iter_label()
        self.iter_slider.valueChanged.connect(self._update_iter_label)
        if mode == "encrypt":
            options.addWidget(QLabel("KDF cost"))
            options.addWidget(self.iter_slider, 1)
            options.addWidget(self.iter_label)
        else:
            hint = QLabel("Iterations are read from the image header automatically")
            hint.setStyleSheet("color:#888;")
            options.addWidget(hint)
            options.addStretch(1)
        self.iter_slider.setVisible(mode == "encrypt")
        self.iter_label.setVisible(mode == "encrypt")
        layout.addLayout(options)

        out_row = QHBoxLayout()
        out_edit = QLineEdit(self.settings.output_dir)
        out_edit.setPlaceholderText("Output folder (empty = next to input)")
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(lambda: self._pick_out_dir(out_edit))
        out_row.addWidget(QLabel("Output"))
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
        start_btn.clicked.connect(lambda: self._start_job(mode))
        cancel_btn.clicked.connect(lambda: self._cancel_job(mode))
        progress = QProgressBar()
        progress.setObjectName(f"{mode}_progress")
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
            "Select 1 image for entropy/correlation/histogram — or 2 images "
            "with identical size for NPCR/UACI."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        run_btn = QPushButton("Run analysis")
        run_btn.setObjectName("analyze_run")
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
        self.corr_table = QTableWidget(0, 3)
        self.corr_table.setHorizontalHeaderLabels(
            ["horizontal", "vertical", "diagonal"]
        )
        self.corr_table.verticalHeader().setVisible(True)
        self.results_layout.addWidget(QLabel("Adjacent-pixel correlation"))
        self.results_layout.addWidget(self.corr_table)
        hist_row = QHBoxLayout()
        hist_row.addWidget(QLabel("Histogram channel"))
        self.hist_channel = QComboBox()
        self.hist_channel.currentIndexChanged.connect(self._update_hist)
        hist_row.addWidget(self.hist_channel)
        hist_row.addStretch(1)
        self.results_layout.addLayout(hist_row)
        self.hist_widget = HistogramBars()
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

    def _update_iter_label(self) -> None:
        value = self.iter_slider.value() * 50_000
        self.iter_label.setText(f"{value:,} iterations")
        self.iter_label.setMinimumWidth(140)

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
        label.setPixmap(
            pix.scaled(label.size() * 0.98, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        box.setTitle(f"{which} — {os.path.basename(path)}")

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
            iterations = self.iter_slider.value() * 50_000
            self.settings.iterations = iterations
        else:
            iterations = self.settings.iterations  # unused for decrypt
        out_dir = getattr(self, f"_{mode}_out").text().strip()
        self.settings.output_dir = out_dir

        self._set_preview("before", files[0])
        self.preview_after._label.setText("(pending)")  # type: ignore[attr-defined]

        self._job = JobWorker(mode, files, passphrase, iterations, out_dir)
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

    def _on_file_done(self, path: str, status: str) -> None:
        if status.startswith("ok: "):
            out_path = status[4:]
            self._last_output_path = out_path
            self._set_preview("after", out_path)
            self.statusBar().showMessage(f"Saved {out_path}", 8000)
        else:
            self.statusBar().showMessage(f"{os.path.basename(path)}: {status}", 10000)
            if "error" in status:
                QMessageBox.warning(self, "Job error", f"{path}\n{status}")

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
        self.hist_channel.addItems(list(self._hist_data.keys()))
        self.hist_channel.blockSignals(False)
        self._update_hist()
        self.statusBar().showMessage(
            f"Analysis complete on backend: {data['backend']}", 8000
        )

    def _update_hist(self) -> None:
        key = self.hist_channel.currentText()
        if key and key in self._hist_data:
            self.hist_widget.set_counts(self._hist_data[key])

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
