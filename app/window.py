"""
app.window
==========

The OptiCipher Desktop main window.

Layout
------
    ┌────────────┬───────────────────────────────────────────────────┐
    │  sidebar   │  header bar  (theme toggle · settings)           │
    │  brand     ├───────────────────────────────────────────────────┤
    │  nav items │                                                   │
    │            │  page (one at a time)                             │
    │  device    │                                                   │
    ├────────────┴───────────────────────────────────────────────────┤
    │  status bar                                                  │
    └──────────────────────────────────────────────────────────────┘

Responsibilities
----------------
The window is the *coordinator*. It owns the workers, the settings, the
session history and the theme manager, and it wires the pages' signals to
them. The pages themselves collect input and render results; they never
call the library directly.

All heavy work happens in `app.workers` QThreads; this module is
presentation and wiring only. Compute settings chosen here are persisted
via `app.settings.AppSettings` and pushed into `opticipher.accel`, so the
next job runs on the selected device/threads/RAM budget.

Compatibility
-------------
The names the previous version of this window exposed (``file_lists``,
``_encrypt_pass``, ``device_label``, ``_on_file_done`` …) are still here —
either as attributes or as properties — so existing scripts and tests keep
working against the redesigned UI.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opticipher import __version__ as _lib_version

from . import charts as _charts
from . import device as _device
from . import icons as _icons
from .history import SessionHistory
from .imaging import ClickableLabel, ImageViewer, describe_image, human_size
from .pages import (
    AboutPage,
    AnalyzePage,
    DecryptPage,
    EncryptPage,
    HistoryPage,
    OverviewPage,
    SettingsPage,
    VerifyPage,
)
from .pages.settings_page import SettingsPanel
from .sftp import is_sftp_output, parse_sftp_url
from .settings import AppSettings
from .shell import HeaderBar, Sidebar
from .theme import (
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    ThemeManager,
)
from .widgets import FileList, GhostButton, IconButton
from .workers import AnalyzeWorker, JobWorker, VerifyWorker, detect_opticipher_header

__all__ = [
    "MainWindow",
    "SettingsDialog",
    "ClickableLabel",
    "FileList",
    "ImageViewer",
    "describe_image",
    "human_size",
    "detect_opticipher_header",
]


# ---------------------------------------------------------------------------
# Settings dialog (kept: the same fields, now built from the shared panel).
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    """Compute + crypto settings; on accept they persist and apply live."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — OptiCipher Desktop")
        self.setMinimumWidth(460)

        self.panel = SettingsPanel(self)
        # Kept as direct attributes: scripts and tests read them.
        self.device_combo = self.panel.device_combo
        self.threads_spin = self.panel.threads_spin
        self.ram_spin = self.panel.ram_spin
        self.iter_spin = self.panel.iter_spin

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(self.panel)
        layout.addWidget(buttons)

    def accept(self) -> None:  # noqa: N802 (Qt naming)
        self.panel.apply()
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
        self.setMinimumWidth(440)
        from .widgets import Card, Field, PasswordField

        card = Card("SFTP credentials", target.describe())
        self.user_edit = QLineEdit(target.user)
        self.user_edit.setToolTip(
            "Account on the SFTP server; leave empty to use your login name"
        )
        card.body.addWidget(Field("User", self.user_edit, "", self))

        self.password_edit = PasswordField(
            "Password (session only)",
            "Held in memory for this run of OptiCipher only — never saved to "
            "settings, disk or logs",
        )
        card.body.addWidget(Field("Password", self.password_edit, "", self))

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText(
            "Optional: path to a private key (used instead of a password)"
        )
        self.key_edit.setToolTip("Browse for an SSH private key file")
        key_browse = GhostButton("…")
        key_browse.setToolTip("Browse for an SSH private key file")
        key_browse.clicked.connect(self._pick_key)
        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(8)
        key_layout.addWidget(self.key_edit, 1)
        key_layout.addWidget(key_browse)
        card.body.addWidget(Field("Key file", key_row, "", self))

        note = QLabel(
            "Kept in memory for this session only — never written to disk."
        )
        note.setObjectName("Faint")
        note.setWordWrap(True)
        card.body.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(card)
        layout.addWidget(buttons)

    def _pick_key(self) -> None:
        from PySide6.QtWidgets import QFileDialog

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
    """The application shell."""

    def __init__(self) -> None:
        super().__init__()
        from . import __version__ as _app_version

        self.setWindowTitle(f"OptiCipher Desktop {_app_version}")
        self.resize(1280, 800)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.setAcceptDrops(True)

        self.settings = AppSettings()
        self.settings.apply_to_accel()

        self.theme_manager = ThemeManager(self.settings)
        self.theme_manager.theme_changed.connect(self._on_theme_changed)
        self.theme_manager.apply()

        self.history = SessionHistory()

        self._job: Optional[JobWorker] = None
        self._analyze: Optional[AnalyzeWorker] = None
        self._verify: Optional[VerifyWorker] = None
        self._last_output_path: Optional[str] = None
        # SFTP credentials for THIS RUN ONLY (never QSettings — see
        # SftpCredentialsDialog). Keyed by (host, port, user).
        self._sftp_sessions: dict = {}
        # (path, reason) pairs for the batch summary dialog.
        self._job_failures: list = []

        self._build_ui()
        self._apply_theme_visuals()
        self._refresh_device_bar()
        self.navigate("overview")
        self.statusBar().showMessage(
            "Ready — drop images anywhere to add them"
        )

    # -- lifecycle ----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """
        Break the window <-> page reference cycle on close.

        Each page holds a back-reference to the window; without breaking it
        the whole shell stays alive until the garbage collector gets to it,
        and every live window is re-styled whenever the theme changes.
        """
        for page in self._pages.values():
            page.window = None
        super().closeEvent(event)

    # -- construction -------------------------------------------------------
    def _build_ui(self) -> None:
        # -- sidebar ----------------------------------------------------------
        self.sidebar = Sidebar()
        self.sidebar.add_section(
            "Workspace",
            [
                ("overview", "Overview", "layers"),
                ("encrypt", "Encrypt", "lock"),
                ("decrypt", "Decrypt", "unlock"),
                ("verify", "Verify", "shield"),
                ("analyze", "Analyze", "chart"),
            ],
        )
        self.sidebar.add_section("Activity", [("history", "History", "clock")])
        self.sidebar.add_section(
            "System",
            [("settings", "Settings", "gear"), ("about", "About", "info")],
        )
        self.sidebar.navigated.connect(self.navigate)

        # -- device summary (sidebar footer) ----------------------------------
        self.device_label = QLabel("")
        self.device_label.setObjectName("Muted")
        self.device_label.setWordWrap(True)
        self.device_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.device_label.setToolTip(
            "Acceleration backend in use (GPU via WebGPU, or CPU fallback) "
            "and its thread settings — change it in Settings"
        )
        device_button = GhostButton("Computer settings…")
        device_button.setToolTip("Open the Settings page")
        device_button.clicked.connect(lambda: self.navigate("settings"))
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(4)
        footer_layout.addWidget(self.device_label)
        footer_layout.addWidget(device_button)
        self.sidebar.add_footer(footer)

        # -- header -----------------------------------------------------------
        self.header = HeaderBar()
        self.theme_btn = IconButton(
            "sun", "Switch to the light theme", self, size=18
        )
        self.theme_btn.setObjectName("theme_toggle")
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.settings_btn = IconButton(
            "gear", "Open Settings", self, size=18
        )
        self.settings_btn.setObjectName("settings_open")
        self.settings_btn.clicked.connect(lambda: self.navigate("settings"))
        self.header.add_right(self.theme_btn)
        self.header.add_right(self.settings_btn)

        # -- pages -------------------------------------------------------------
        self.overview_page = OverviewPage(self)
        self.encrypt_page = EncryptPage(self)
        self.decrypt_page = DecryptPage(self)
        self.verify_page = VerifyPage(self)
        self.analyze_page = AnalyzePage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)
        self.about_page = AboutPage(self)
        self._pages = {
            page.key: page
            for page in (
                self.overview_page,
                self.encrypt_page,
                self.decrypt_page,
                self.verify_page,
                self.analyze_page,
                self.history_page,
                self.settings_page,
                self.about_page,
            )
        }
        self._page_order = [
            "overview",
            "encrypt",
            "decrypt",
            "verify",
            "analyze",
            "history",
            "settings",
            "about",
        ]

        self.stack = QStackedWidget()
        for key in self._page_order:
            self.stack.addWidget(self._pages[key])

        # -- wiring ------------------------------------------------------------
        self.encrypt_page.files.selection_changed.connect(self._on_source_selected)
        self.decrypt_page.files.selection_changed.connect(self._on_source_selected)
        self.verify_page.files.selection_changed.connect(self._on_source_selected)
        self.analyze_page.files.selection_changed.connect(self._on_source_selected)

        self.encrypt_page.start_btn.clicked.connect(lambda: self._start_job("encrypt"))
        self.encrypt_page.cancel_btn.clicked.connect(lambda: self._cancel_job("encrypt"))
        self.decrypt_page.start_btn.clicked.connect(lambda: self._start_job("decrypt"))
        self.decrypt_page.cancel_btn.clicked.connect(lambda: self._cancel_job("decrypt"))
        self.verify_page.verify_btn.clicked.connect(self._start_verify)
        self.analyze_page.run_btn.clicked.connect(self._start_analyze)

        # -- central widget ------------------------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.header)
        right_layout.addWidget(self.stack, 1)

        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.sidebar)
        shell.addWidget(right, 1)
        self.setCentralWidget(central)

        self._build_menu()
        self._build_shortcuts()
        self.setStatusBar(self._make_status_bar())

        # -- compatibility attributes -----------------------------------------
        self.file_lists = {
            "encrypt": self.encrypt_page.files,
            "decrypt": self.decrypt_page.files,
        }
        self.analyze_files = self.analyze_page.files
        self.verify_files = self.verify_page.files
        self.encrypt_tab = self.encrypt_page
        self.decrypt_tab = self.decrypt_page
        self._encrypt_pass = self.encrypt_page.pass_field.edit
        self._encrypt_confirm = self.encrypt_page.confirm_field.edit
        self._encrypt_out = self.encrypt_page.out_edit
        self._decrypt_pass = self.decrypt_page.pass_field.edit
        self._decrypt_out = self.decrypt_page.out_edit
        self._enc_iter_slider = self.encrypt_page.kdf_slider
        self._enc_iter_label = self.encrypt_page.kdf_label

    def _make_status_bar(self):
        from PySide6.QtWidgets import QStatusBar

        bar = QStatusBar()
        bar.setSizeGripEnabled(True)
        return bar

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_act = QAction("Add images…", self)
        open_act.triggered.connect(self._add_images_dialog)
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        go_menu = self.menuBar().addMenu("&Go")
        for index, key in enumerate(self._page_order, start=1):
            page = self._pages[key]
            action = QAction(page.title, self)
            action.setShortcut(QKeySequence(f"Alt+{index}"))
            action.triggered.connect(lambda _checked=False, k=key: self.navigate(k))
            go_menu.addAction(action)

        settings_menu = self.menuBar().addMenu("&Settings")
        conf_act = QAction("Compute & crypto…", self)
        conf_act.triggered.connect(self._open_settings)
        settings_menu.addAction(conf_act)
        theme_menu = settings_menu.addMenu("Theme")
        self.dark_action = QAction("Dark", self, checkable=True)
        self.light_action = QAction("Light", self, checkable=True)
        self.dark_action.triggered.connect(lambda: self._set_theme("dark"))
        self.light_action.triggered.connect(lambda: self._set_theme("light"))
        theme_menu.addAction(self.dark_action)
        theme_menu.addAction(self.light_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._about)
        help_menu.addAction(about_act)

    def _build_shortcuts(self) -> None:
        """Alt+1..Alt+8 jump between the pages (keyboard navigation)."""
        for index, key in enumerate(self._page_order, start=1):
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Alt+{index}"))
            action.setShortcutContext(Qt.WindowShortcut)
            action.triggered.connect(lambda _checked=False, k=key: self.navigate(k))
            self.addAction(action)

    # -- navigation ---------------------------------------------------------
    def navigate(self, key: str) -> None:
        """Show the page registered under `key`."""
        page = self._pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.sidebar.set_current(key)
        try:
            page.refresh()
        except Exception:  # noqa: BLE001 - a page must never break navigation
            pass

    def _current_page(self):
        return self.stack.currentWidget()

    def _current_key(self) -> str:
        page = self._current_page()
        return getattr(page, "key", "")

    # -- theme --------------------------------------------------------------
    def _toggle_theme(self) -> None:
        self.theme_manager.toggle()

    def _set_theme(self, name: str) -> None:
        self.theme_manager.set_theme(name)

    def _on_theme_changed(self, name: str) -> None:
        self._apply_theme_visuals()

    def _apply_theme_visuals(self) -> None:
        """Re-tint the parts of the UI that are drawn, not styled."""
        palette = self.theme_manager.palette
        _charts.set_theme_colors(palette)
        self.sidebar.recolor(palette.text_dim)
        self.sidebar.brand_icon.setPixmap(
            _icons.pixmap("shield", palette.accent, 26)
        )
        self.theme_btn.recolor(palette.text_dim)
        self.settings_btn.recolor(palette.text_dim)
        target = "sun" if self.theme_manager.is_dark else "moon"
        self.theme_btn.setIcon(_icons.icon(target, palette.text_dim, 18))
        self.theme_btn.setToolTip(
            "Switch to the light theme"
            if self.theme_manager.is_dark
            else "Switch to the dark theme"
        )
        self.overview_page.recolor(palette)
        self.analyze_page.hist_widget.update()
        for bar in self.analyze_page.metric_bars.values():
            bar.update()
        self.dark_action.setChecked(self.theme_manager.is_dark)
        self.light_action.setChecked(not self.theme_manager.is_dark)

    # -- compatibility properties -------------------------------------------
    @property
    def iter_slider(self):
        """The Encrypt page's KDF-cost slider (kept for scripts and tests)."""
        return self._enc_iter_slider

    @property
    def iter_label(self):
        """The Encrypt page's KDF-cost value label."""
        return self._enc_iter_label

    @property
    def info_label(self):
        """The metadata panel of the Encrypt page's preview."""
        return self.encrypt_page.preview.info_label

    @property
    def preview_before(self):
        """The 'original' preview box."""
        return self.encrypt_page.preview.before

    @property
    def preview_after(self):
        """The 'result' preview box."""
        return self.encrypt_page.preview.after

    @property
    def hist_channel(self):
        return self.analyze_page.hist_channel

    @property
    def hist_widget(self):
        return self.analyze_page.hist_widget

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
            target = self._active_file_list()
            if target is not None:
                target.add_paths(paths)
                self.statusBar().showMessage(f"Added {len(paths)} file(s)")

    # -- helpers ------------------------------------------------------------
    def _active_file_list(self) -> Optional[FileList]:
        """The file list of the page the user is on."""
        page = self._current_page()
        files = getattr(page, "files", None)
        if isinstance(files, FileList):
            return files
        return self.analyze_files

    def _add_images_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from .widgets import IMAGE_FILTER

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add images", self.settings.last_dir, IMAGE_FILTER
        )
        if paths:
            self.settings.last_dir = os.path.dirname(paths[0])
            target = self._active_file_list()
            if target is not None:
                target.add_paths(paths)

    def _open_settings(self) -> None:
        if SettingsDialog(self).exec() == QDialog.Accepted:
            self._refresh_device_bar()
            self.statusBar().showMessage("Settings applied", 4000)

    def refresh_device_summary(self) -> None:
        self._refresh_device_bar()

    def _refresh_device_bar(self) -> None:
        from opticipher import accel

        cfg = accel.get_config()
        backend = accel.get_backend()
        info = backend.info()
        detail = info.get("detail", backend.name)
        ram = _device.total_ram_mb()
        self.device_label.setText(
            f"Device: {detail}\n"
            f"{cfg['resolved_threads']} threads   ·   "
            f"{cfg['resolved_ram_mb']} MiB budget\n"
            f"system RAM: {ram / 1024:.1f} GiB"
        )

    # -- previews -----------------------------------------------------------
    def _set_preview(self, which: str, path: str) -> None:
        """Show `path` in every preview panel (the source or the result)."""
        for page in (self.encrypt_page, self.decrypt_page, self.verify_page):
            panel = getattr(page, "preview", None)
            if panel is None:
                continue
            box = panel.before if which == "before" else panel.after
            if box is None:
                continue
            box.set_image(path)
        if which == "before":
            self.encrypt_page.preview.set_info(describe_image(path))

    def _clear_preview(self, which: str) -> None:
        for page in (self.encrypt_page, self.decrypt_page, self.verify_page):
            panel = getattr(page, "preview", None)
            if panel is None:
                continue
            box = panel.before if which == "before" else panel.after
            if box is None:
                continue
            box.clear()
        if which == "before":
            self.encrypt_page.preview.set_info("")

    def _on_source_selected(self, path: str) -> None:
        """Show the selected source immediately — before any job runs."""
        if path:
            self._set_preview("before", path)
        else:
            self._clear_preview("before")

    def _enlarge(self, which: str) -> None:
        """Open the enlarge viewer for a preview (click-to-enlarge)."""
        page = self._current_page()
        panel = getattr(page, "preview", None) or self.encrypt_page.preview
        box = panel.before if which == "before" else panel.after
        path = getattr(box, "_path", None)
        if not path:
            return
        viewer = ImageViewer(path, describe_image(path), self)
        viewer.setWindowTitle(f"{which} — {os.path.basename(path)}")
        viewer.exec()

    # -- encrypt / decrypt jobs ---------------------------------------------
    def _start_job(self, mode: str) -> None:
        if self._job is not None and self._job.isRunning():
            return
        page = self._pages[mode]
        files = page.files.paths()
        if not files:
            QMessageBox.information(self, "OptiCipher", "Add at least one image first.")
            return
        passphrase = page.pass_field.text()
        if not passphrase:
            QMessageBox.warning(self, "OptiCipher", "Enter a passphrase.")
            return
        if mode == "encrypt":
            confirm = page.confirm_field.text()
            if passphrase != confirm:
                QMessageBox.warning(self, "OptiCipher", "Passphrases do not match.")
                return
            iterations = page.kdf_slider.value() * 50_000
            self.settings.iterations = iterations
        else:
            iterations = self.settings.iterations  # unused for decrypt
        out_dir = page.out_edit.text().strip()
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

        page.reset_steps()
        page.set_running(True)
        page.set_status(f"{mode.capitalize()}ing…")
        self._job_failures = []
        # Remember which job is running: the user may navigate to another
        # page while it works, and the outcome rows must still land on the
        # page that started the job.
        self._active_mode = mode

        self._set_preview("before", files[0])
        page.preview.after.set_pending()

        self._job = JobWorker(
            mode, files, passphrase, iterations, out_dir, sftp=sftp_cfg
        )
        self._job.progress.connect(
            lambda pct, msg, m=mode: self._on_progress(m, pct, msg)
        )
        self._job.file_done.connect(self._on_file_done)
        self._job.all_done.connect(lambda ok, bad, m=mode: self._on_all_done(m, ok, bad))
        self._job.start()

        self.statusBar().showMessage(f"{mode.capitalize()}ing…")

    def _cancel_job(self, mode: str) -> None:
        if self._job is not None:
            self._job.cancel()
            page = self._pages[mode]
            page.set_status("Cancelling after the current file…")
            self.statusBar().showMessage("Cancelling after the current file…", 5000)

    def _on_progress(self, mode: str, pct: int, message: str) -> None:
        page = self._pages.get(mode)
        if page is not None:
            page.set_progress(pct)
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
            self._record_step(path, True, out_path, payload)
        else:
            self.statusBar().showMessage(f"{os.path.basename(path)}: {status}", 10000)
            if "error" in status:
                # Collect instead of popping one modal per file: a batch of
                # failures must not bury the user under dialogs. The full
                # summary lands once, at all_done.
                self._job_failures.append((path, status))
            self._record_step(path, False, None, status)

    def _record_step(self, path: str, ok: bool, output: Optional[str], detail: str) -> None:
        """Update the per-page outcome rows and the session history."""
        name = os.path.basename(path)
        mode = getattr(self, "_active_mode", "") or self._current_key()
        self.history.record(
            mode if mode in ("encrypt", "decrypt", "verify") else "encrypt",
            name,
            "ok" if ok else "error",
            detail,
            output,
        )
        page = self._pages.get(mode)
        if page is None or not hasattr(page, "steps"):
            return
        if page.mode == "decrypt":
            if ok:
                page.set_step("Authentication (HMAC-SHA256)", "verified", "success")
                page.set_step("Output written", output or "—", "success")
                page.set_step(
                    "Exact restoration",
                    "bit-exact (authenticated plaintext)",
                    "success",
                )
            else:
                if "integrity check failed" in detail:
                    page.set_step(
                        "Authentication (HMAC-SHA256)", "failed", "error"
                    )
                else:
                    page.set_step(
                        "Authentication (HMAC-SHA256)", "not reached", "warning"
                    )
                page.set_step("Output written", "not written", "error")
                page.set_step("Exact restoration", "not reached", "warning")
        else:
            page.set_step("Files processed", name, "success" if ok else "error")
            page.set_step(
                "Result written", output or "—", "success" if ok else "error"
            )
            if "uploaded" in detail:
                page.set_step("Remote copy", "uploaded and verified", "success")
            else:
                page.set_step("Remote copy", "not used", "neutral")

    def _on_all_done(self, mode: str, ok: int, bad: int) -> None:
        page = self._pages.get(mode)
        if page is not None:
            page.set_running(False)
            page.set_progress(100)
            page.set_status(f"Finished: {ok} succeeded, {bad} failed/cancelled")
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

    # -- verify -------------------------------------------------------------
    def _start_verify(self) -> None:
        if self._verify is not None and self._verify.isRunning():
            return
        path = self.verify_page.files.current_path()
        if not path:
            QMessageBox.information(
                self, "OptiCipher", "Choose a file to verify first."
            )
            return
        passphrase = self.verify_page.pass_field.text().strip() or None
        self.verify_page.reset()
        self.verify_page.progress.setVisible(True)
        self.verify_page.verify_btn.setEnabled(False)
        self.verify_page.set_status("Checking…")
        self.statusBar().showMessage("Verifying…")

        self._verify = VerifyWorker(path, passphrase)
        self._verify.result.connect(self._on_verify_result)
        self._verify.failed.connect(self._on_verify_failed)
        self._verify.start()

    def _on_verify_result(self, payload: dict) -> None:
        self.verify_page.progress.setVisible(False)
        self.verify_page.verify_btn.setEnabled(True)
        self.verify_page.show_result(payload)
        ok = bool(payload.get("ok"))
        name = os.path.basename(payload.get("path", ""))
        self.verify_page.set_status(payload.get("message", ""))
        self.statusBar().showMessage(f"{name}: {payload.get('message', '')}", 10000)
        self.history.record(
            "verify",
            name,
            "ok" if ok else "error",
            payload.get("message", ""),
        )

    def _on_verify_failed(self, message: str) -> None:
        self.verify_page.progress.setVisible(False)
        self.verify_page.verify_btn.setEnabled(True)
        self.verify_page.set_status("The file could not be read.")
        QMessageBox.warning(self, "Verification error", message)

    # -- analyze ------------------------------------------------------------
    def _start_analyze(self) -> None:
        if self._analyze is not None and self._analyze.isRunning():
            return
        files = self.analyze_page.files.paths()
        if not files:
            QMessageBox.information(self, "OptiCipher", "Add at least one image first.")
            return
        self.statusBar().showMessage("Analyzing…")
        self.analyze_page.set_status("Analyzing…")
        self._analyze = AnalyzeWorker(files)
        self._analyze.result.connect(self._on_analyze_result)
        self._analyze.failed.connect(
            lambda msg: QMessageBox.warning(self, "Analyze error", msg)
        )
        self._analyze.start()

    def _on_analyze_result(self, data: dict) -> None:
        self.analyze_page.show_result(data)
        self.analyze_page.set_status(f"Analysis complete on backend: {data['backend']}")
        self.statusBar().showMessage(
            f"Analysis complete on backend: {data['backend']}", 8000
        )

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
