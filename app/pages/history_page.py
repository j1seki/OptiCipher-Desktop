"""Separate event logs and completed job review pages."""

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..history import timestamp_text
from ..widgets import Card, SecondaryButton
from .base import BasePage


class HistoryPage(BasePage):
    key = "history"
    title = "Logs"
    subtitle = "Follow app operations and copy the event log."

    def __init__(self, window=None, parent=None):
        super().__init__(window, parent)
        history = getattr(window, "history", None)
        self.preferences = history.settings if history else None

        logs = Card("Event log")
        toolbar = QHBoxLayout()
        self.wrap = QCheckBox("Wrap lines")
        self.wrap.setChecked(self._preference("wrap"))
        self.wrap.setToolTip("Wrap long log lines to the width of the viewer")
        self.wrap.toggled.connect(lambda checked: self._toggle("wrap", checked))
        toolbar.addWidget(self.wrap)
        self.timestamps = QCheckBox("Timestamps")
        self.timestamps.setChecked(self._preference("timestamps"))
        self.timestamps.setToolTip("Show a local date and time on each log entry")
        self.timestamps.toggled.connect(lambda checked: self._toggle("timestamps", checked))
        toolbar.addWidget(self.timestamps)
        toolbar.addStretch()
        self.copy_logs = SecondaryButton("Copy logs")
        self.copy_logs.setToolTip("Copy the selection or the full log to the clipboard")
        self.copy_logs.clicked.connect(self._copy)
        toolbar.addWidget(self.copy_logs)
        self.clear = SecondaryButton("Clear log")
        self.clear.setObjectName("history_clear")
        self.clear.setToolTip("Clear the event log and keep the job records")
        self.clear.clicked.connect(self._confirm_clear)
        toolbar.addWidget(self.clear)
        logs.body.addLayout(toolbar)

        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.viewer.setAccessibleName("Event log")
        self.viewer.setPlaceholderText("No log entries yet")
        logs.body.addWidget(self.viewer)
        self.content.addWidget(logs, 1)
        self.refresh()

    def _preference(self, name):
        return self.preferences.value(f"activity/{name}", True, bool) if self.preferences is not None else True

    def _toggle(self, name, checked):
        if self.preferences is not None:
            self.preferences.setValue(f"activity/{name}", checked)
        self._refresh_log()

    def _refresh_log(self):
        history = getattr(self.window, "history", None)
        entries = history.entries if history else []
        self.viewer.setLineWrapMode(QPlainTextEdit.WidgetWidth if self.wrap.isChecked() else QPlainTextEdit.NoWrap)
        text = "\n".join(entry.log_line(self.timestamps.isChecked()) for entry in entries)
        if text != self.viewer.toPlainText():
            vertical = self.viewer.verticalScrollBar()
            position = vertical.value()
            at_end = position == vertical.maximum()
            cursor = self.viewer.textCursor()
            anchor, end = cursor.anchor(), cursor.position()
            self.viewer.setPlainText(text)
            if anchor != end:
                selection = self.viewer.textCursor()
                limit = self.viewer.document().characterCount() - 1
                selection.setPosition(min(anchor, limit))
                selection.setPosition(min(end, limit), QTextCursor.KeepAnchor)
                self.viewer.setTextCursor(selection)
            vertical.setValue(vertical.maximum() if at_end else position)
        self.copy_logs.setEnabled(bool(entries))
        self.clear.setEnabled(bool(entries))

    def refresh(self):
        self._refresh_log()

    def _copy(self):
        cursor = self.viewer.textCursor()
        text = cursor.selectedText().replace("\u2029", "\n") if cursor.hasSelection() else self.viewer.toPlainText()
        QApplication.clipboard().setText(text)

    def _confirm_clear(self):
        answer = QMessageBox.question(self, "Clear log", "Clear all log entries?", QMessageBox.Yes | QMessageBox.Cancel)
        if answer == QMessageBox.Yes:
            self._clear()

    def _clear(self):
        history = getattr(self.window, "history", None)
        if history is not None:
            history.clear()
        self.refresh()


class JobHistoryPage(BasePage):
    key = "jobs"
    title = "Job history"
    subtitle = "Open a batch or folder scan to review its per-file outcomes."

    def __init__(self, window=None, parent=None):
        super().__init__(window, parent)
        history = getattr(window, "history", None)
        jobs = Card("Job history")
        self.review_button = SecondaryButton("Review job")
        self.review_button.setToolTip("Open the selected job and review its per-file results")
        self.review_button.clicked.connect(self._review)
        jobs.set_header_widget(self.review_button)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Job", "Started", "Result", "Review"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_review)
        self.table.cellDoubleClicked.connect(lambda *_: self._review())
        jobs.body.addWidget(self.table)
        self.empty = QLabel("No jobs yet")
        jobs.body.addWidget(self.empty)

        keep = QCheckBox("Keep logs and jobs after closing")
        keep.setToolTip("Store filenames and job outcomes in local application settings")
        if history is not None:
            keep.setChecked(history.persistent)
            keep.toggled.connect(history.set_persistent)
        jobs.body.addWidget(keep)

        self.content.addWidget(jobs, 1)
        self.refresh()

    def _log_preference(self, name):
        settings = self.window.history.settings
        return settings.value(f"activity/{name}", True, bool) if settings is not None else True

    def refresh(self):
        history = getattr(self.window, "history", None)
        jobs = history.jobs if history else []
        selected = self._selected_id()
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(jobs))
            row_to_select = 0
            for row, job in enumerate(jobs):
                if job.id == selected:
                    row_to_select = row
                review = "Confirmed" if job.reviewed else "Pending" if job.finished else "Running"
                for column, value in enumerate((job.name, timestamp_text(job.started), job.summary, review)):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, job.id)
                    item.setToolTip(value)
                    self.table.setItem(row, column, item)
            if jobs:
                self.table.selectRow(row_to_select)
        self.table.setVisible(bool(jobs))
        self.empty.setVisible(not jobs)
        self._update_review()

    def _selected_id(self):
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item is not None else None

    def _update_review(self):
        self.review_button.setEnabled(self._selected_id() is not None)

    def _review(self):
        job_id = self._selected_id()
        job = next((item for item in self.window.history.jobs if item.id == job_id), None)
        if job is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(job.name)
        dialog.resize(680, 420)
        layout = QVBoxLayout(dialog)
        summary = QLabel(f"{timestamp_text(job.started)} · {job.summary}")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        entries = [entry.log_line(self._log_preference("timestamps")) for entry in job.outcomes]
        details = QPlainTextEdit("\n".join(entries) or "No file outcomes recorded.")
        details.setAccessibleName("Job results")
        details.setReadOnly(True)
        details.setLineWrapMode(QPlainTextEdit.WidgetWidth if self._log_preference("wrap") else QPlainTextEdit.NoWrap)
        layout.addWidget(details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy = buttons.addButton("Copy results", QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(f"{job.name}\n{summary.text()}\n{details.toPlainText()}"))
        confirm = buttons.addButton("Confirm review", QDialogButtonBox.AcceptRole)
        confirm.setEnabled(job.finished is not None and job.reviewed is None)
        if job.reviewed:
            confirm.setText("Review confirmed")
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.window.history.confirm_review(job.id)
