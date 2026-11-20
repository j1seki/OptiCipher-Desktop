"""Configuration and activity for desktop folder watches."""

from PySide6.QtCore import QTime, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QTabWidget, QTimeEdit,
    QVBoxLayout, QWidget,
)

from ..private_storage import private_folder
from ..watch import MODES, WatchConfig
from ..widgets import Card, PasswordField
from .base import BasePage


class WatchEditor(QWidget):
    def __init__(self, watcher, mode):
        super().__init__()
        self.watcher = watcher
        self.mode = mode
        layout = QVBoxLayout(self)
        folders = Card("Folders")
        self.folders = folders
        paths = QFormLayout()
        self.inbox = self._folder_picker(paths, "Input folder")
        self.output = self._folder_picker(paths, "Output folder")
        self.output.setPlaceholderText("Private folder")
        folders.body.addLayout(paths)
        open_private = QPushButton("Open private folder")
        open_private.setToolTip("Show the private application data folder")
        open_private.clicked.connect(self._open_private)
        folders.body.addWidget(open_private)
        layout.addWidget(folders)

        schedule = Card("Schedule")
        form = QFormLayout()
        self.interval = QComboBox()
        self.interval.setToolTip("How often to scan the input folder")
        for label, minutes in (
            ("Every 15 minutes", 15), ("Every hour", 60), ("Every 6 hours", 360),
            ("Every 12 hours", 720), ("Daily", 1440), ("Weekly", 0),
        ):
            self.interval.addItem(label, minutes)
        form.addRow("Repeat", self.interval)
        self.day = QComboBox()
        self.day.setToolTip("Local weekday for weekly checks")
        self.day.addItems(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        self.clock = QTimeEdit(QTime(9, 0))
        self.clock.setToolTip("Local time for weekly checks")
        self.clock.setDisplayFormat("HH:mm")
        form.addRow("Weekday", self.day)
        form.addRow("Time", self.clock)
        self.interval.currentIndexChanged.connect(self._schedule_fields)
        schedule.body.addLayout(form)
        self.existing = QCheckBox("Include existing images when enabled")
        self.overwrite = QCheckBox("Overwrite existing output files")
        schedule.body.addWidget(self.existing)
        schedule.body.addWidget(self.overwrite)
        layout.addWidget(schedule)

        credentials = Card("Passphrase")
        self.password = PasswordField("Watch passphrase", "Passphrase used for this inbox")
        self.remember = QCheckBox("Remember in the system credential store")
        self.generate = QPushButton("Generate strong passphrase")
        self.generate.setToolTip("Generate a random passphrase for this watch")
        self.generate.clicked.connect(lambda: self.password.generate())
        self.forget = QPushButton("Forget saved passphrase")
        self.forget.setToolTip("Remove this passphrase from the system credential store")
        self.forget.clicked.connect(self._forget)
        for widget in (self.password, self.generate, self.remember, self.forget):
            credentials.body.addWidget(widget)
        layout.addWidget(credentials)

        controls = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        controls.addWidget(self.status, 1)
        self.run_button = QPushButton("Run now")
        self.run_button.setToolTip("Scan this inbox now")
        self.run_button.clicked.connect(lambda: watcher.run_now(mode))
        controls.addWidget(self.run_button)
        self.enable_button = QPushButton()
        self.enable_button.setToolTip("Turn this independent watch on or off")
        self.enable_button.clicked.connect(self._toggle)
        controls.addWidget(self.enable_button)
        layout.addLayout(controls)
        layout.addStretch()

        config = watcher.configs[mode]
        self.inbox.setText(config.inbox)
        self.output.setText(config.output)
        self.interval.setCurrentIndex(max(0, self.interval.findData(config.interval)))
        self.day.setCurrentIndex(config.weekday)
        self.clock.setTime(QTime.fromString(config.clock, "HH:mm"))
        self.existing.setChecked(config.include_existing)
        self.overwrite.setChecked(config.overwrite)
        self.remember.setChecked(config.remember)
        self._schedule_fields()
        watcher.changed.connect(self._refresh)
        self._refresh(mode)

    def _folder_picker(self, form, label):
        edit = QLineEdit()
        edit.setAccessibleName(label)
        edit.setToolTip(f"Path to the {label.lower()}")
        button = QPushButton("Browse…")
        button.setToolTip(f"Choose the {label.lower()}")

        def select():
            path = QFileDialog.getExistingDirectory(self, label, edit.text())
            if path:
                edit.setText(path)

        button.clicked.connect(select)
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(label, row)
        return edit

    def _schedule_fields(self):
        weekly = self.interval.currentData() == 0
        self.day.setEnabled(weekly and self.mode not in self.watcher.secrets)
        self.clock.setEnabled(weekly and self.mode not in self.watcher.secrets)

    def _open_private(self):
        try:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(private_folder()))):
                raise OSError("Could not open the private folder.")
        except OSError as error:
            QMessageBox.warning(self, "Private folder", str(error))

    def _toggle(self):
        if self.mode in self.watcher.secrets:
            self.watcher.stop(self.mode)
            return
        config = WatchConfig(
            inbox=self.inbox.text().strip(), output=self.output.text().strip(),
            interval=self.interval.currentData(), weekday=self.day.currentIndex(),
            clock=self.clock.time().toString("HH:mm"), include_existing=self.existing.isChecked(),
            overwrite=self.overwrite.isChecked(), remember=self.remember.isChecked(),
        )
        try:
            self.watcher.start(self.mode, config, self.password.text())
        except Exception as error:
            QMessageBox.warning(self, "Folder watch", str(error))

    def _forget(self):
        try:
            self.watcher.forget(self.mode)
        except Exception as error:
            QMessageBox.warning(self, "Credential store", str(error))
        else:
            self.remember.setChecked(False)

    def _refresh(self, mode):
        if mode != self.mode:
            return
        active = mode in self.watcher.secrets
        busy = mode in self.watcher.workers
        self.status.setText(self.watcher.status[mode])
        self.run_button.setEnabled(active and not busy)
        self.enable_button.setText("Turn off" if active else f"Turn on auto-{mode}")
        self.enable_button.setEnabled(active or not busy)
        self.forget.setEnabled(not active and self.watcher.configs[mode].remember)
        for widget in (self.folders, self.interval, self.existing, self.overwrite,
                       self.password, self.generate, self.remember):
            widget.setEnabled(not active and not busy)
        self._schedule_fields()


class WatchPage(BasePage):
    key = "watch"
    title = "Folder watch"
    subtitle = "Schedule separate encrypt and decrypt inboxes while OptiCipher is open."

    def __init__(self, window=None, parent=None):
        super().__init__(window, parent)
        tabs = QTabWidget()
        for mode in MODES:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(WatchEditor(window.watcher, mode))
            tabs.addTab(scroll, f"Auto-{mode}")
        self.content.addWidget(tabs, 1)
