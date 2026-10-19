"""
app.widgets
===========

The reusable component system.

Every visual element of the application is built from the widgets in this
module. They are plain ``QWidget`` subclasses that carry a *role* (an
``objectName``), and the role is what the stylesheet in :mod:`app.theme`
styles. That is why no widget here contains an inline stylesheet: change a
token, and every card, button, badge and field follows.

Contents
--------
    Card            a titled panel (the basic container)
    Divider         a 1px rule
    PrimaryButton / SecondaryButton / GhostButton / IconButton
    StatusBadge     a coloured, labelled status chip (never colour alone)
    Field           a labelled form row with an optional hint
    PasswordField   a secret input with a reveal toggle
    FileList        the batch file list (drop zone + list + controls)
    PreviewBox      one image preview
    PreviewPanel    before/after previews + the metadata panel
    PageHeader      title, subtitle and contextual actions
    EmptyState      "nothing here yet" with a way out
    StatTile        one number + its label
    InfoRow         a label/value pair (value optionally monospace)
    StepRow         one line of a multi-step outcome (label + badge)
    Divider, SectionTitle
"""

from __future__ import annotations

import os
from typing import Iterable, List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .imaging import ClickableLabel, human_size

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"

#: Colours used for the per-channel histogram (image-editor convention).
CHANNEL_COLORS = {
    "channel_0": "#F45F5F",
    "channel_1": "#60D678",
    "channel_2": "#5AAFFF",
    "channel_3": "#F0C454",
}


# ---------------------------------------------------------------------------
# Containers.
# ---------------------------------------------------------------------------
class Card(QFrame):
    """
    A titled panel.

    The card owns its header (title, optional subtitle, optional action
    widget) and exposes ``body`` — a vertical layout the caller fills.
    """

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: Optional[QWidget] = None,
        flat: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CardFlat" if flat else "Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 18)
        outer.setSpacing(12)

        # -- header: title above subtitle, actions on the right --------------
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self._title_label = QLabel(title)
        self._title_label.setObjectName("SectionTitle")
        self._subtitle_label = QLabel(subtitle)
        self._subtitle_label.setObjectName("Faint")
        self._subtitle_label.setWordWrap(True)
        self._subtitle_label.setVisible(bool(subtitle))
        titles.addWidget(self._title_label)
        titles.addWidget(self._subtitle_label)
        self.header.addLayout(titles, 1)
        self.header_widget: Optional[QWidget] = None
        if title or subtitle:
            outer.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)
        # Anything left over belongs at the bottom of the card, not between
        # the header and the content.
        outer.addStretch(1)

    # -- header -------------------------------------------------------------
    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setVisible(bool(subtitle))

    def set_header_widget(self, widget: QWidget) -> None:
        """Put a widget (e.g. a button) at the right end of the header."""
        if self.header_widget is not None:
            self.header.removeWidget(self.header_widget)
            self.header_widget.setParent(None)
        self.header_widget = widget
        if widget is not None:
            self.header.addWidget(widget, 0, Qt.AlignTop)


class Divider(QFrame):
    """A 1px horizontal rule."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class SectionTitle(QLabel):
    """A small section heading."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


# ---------------------------------------------------------------------------
# Buttons.
# ---------------------------------------------------------------------------
class PrimaryButton(QPushButton):
    """The single most important action on a screen."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Primary")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)


class SecondaryButton(QPushButton):
    """A supporting action."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Secondary")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)


class GhostButton(QPushButton):
    """A low-emphasis action (toolbar-ish)."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Ghost")
        self.setCursor(Qt.PointingHandCursor)


class IconButton(QPushButton):
    """
    A square, icon-only button.

    Icon-only buttons still need an accessible name, so the constructor takes
    a tooltip that doubles as the accessible description.
    """

    def __init__(
        self,
        icon_name: str,
        tooltip: str,
        parent: Optional[QWidget] = None,
        color: str = "#A0A9B8",
        size: int = 18,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("IconButton")
        self.setIcon(icons.icon(icon_name, color, size))
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self._icon_name = icon_name
        self._color = color

    def recolor(self, color: str, size: Optional[int] = None) -> None:
        """Re-tint the glyph (used when the theme changes)."""
        self._color = color
        current = self.iconSize().width() or 18
        self.setIcon(icons.icon(self._icon_name, color, size or current))
        self.setIconSize(QSize(size or current, size or current))


# ---------------------------------------------------------------------------
# Status.
# ---------------------------------------------------------------------------
class StatusBadge(QLabel):
    """
    A small, labelled status chip.

    The text always states the state, so the badge never relies on colour
    alone — which also keeps it readable for colour-blind users and in
    high-contrast modes.
    """

    VARIANTS = {
        "success": ("BadgeSuccess", "check"),
        "error": ("BadgeError", "cross"),
        "warning": ("BadgeWarning", "alert"),
        "info": ("BadgeInfo", "info"),
        "neutral": ("BadgeNeutral", "info"),
    }

    def __init__(
        self,
        text: str = "",
        variant: str = "neutral",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self.setAlignment(Qt.AlignCenter)
        # A badge sizes to its text; it must never stretch across its row.
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.apply_variant(variant)

    def apply_variant(self, variant: str) -> None:
        self._variant = variant
        style, glyph = self.VARIANTS.get(variant, self.VARIANTS["neutral"])
        self.setObjectName(style)
        self.setProperty("glyph", glyph)

    def set_status(self, text: str, variant: str) -> None:
        self.setText(text)
        self.apply_variant(variant)


# ---------------------------------------------------------------------------
# Form fields.
# ---------------------------------------------------------------------------
class Field(QWidget):
    """
    A labelled form control.

    ``label`` sits above the control, ``hint`` below it in secondary text.
    Both the label and the control carry the same tooltip, so hovering
    either one explains the setting.
    """

    def __init__(
        self,
        label: str,
        control: QWidget,
        hint: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.label = QLabel(label)
        self.label.setObjectName("FieldLabel")
        self.control = control
        layout.addWidget(self.label)
        layout.addWidget(control)

        self.hint = QLabel(hint)
        self.hint.setObjectName("Faint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        layout.addWidget(self.hint)

        if hint:
            self.label.setToolTip(hint)
            control.setToolTip(hint)

    def set_hint(self, hint: str) -> None:
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        if hint:
            self.label.setToolTip(hint)
            self.control.setToolTip(hint)

    def set_label(self, text: str) -> None:
        self.label.setText(text)


class PasswordField(QWidget):
    """
    A passphrase input with a reveal toggle.

    The toggle is a real button (keyboard reachable, with an accessible
    name); the secret is masked by default.
    """

    def __init__(
        self,
        placeholder: str = "Passphrase",
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText(placeholder)
        if tooltip:
            self.edit.setToolTip(tooltip)
        self.edit.setAccessibleName(placeholder)
        layout.addWidget(self.edit, 1)

        self.reveal = IconButton("eye", "Show passphrase", self, size=16)
        self.reveal.setFixedSize(32, 32)
        self.reveal.setCheckable(True)
        self.reveal.toggled.connect(self._on_toggled)
        layout.addWidget(self.reveal)

    def _on_toggled(self, checked: bool) -> None:
        self.edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.reveal.setToolTip("Hide passphrase" if checked else "Show passphrase")
        self.reveal.setAccessibleName(self.reveal.toolTip())

    def text(self) -> str:
        return self.edit.text()

    def setText(self, value: str) -> None:  # noqa: N802 (Qt-ish naming)
        self.edit.setText(value)

    def set_tool_tip(self, text: str) -> None:
        self.edit.setToolTip(text)

    def set_placeholder(self, text: str) -> None:
        self.edit.setPlaceholderText(text)

    def setTextInteractionFlags(self, flags) -> None:  # noqa: N802
        self.edit.setTextInteractionFlags(flags)


class InfoRow(QWidget):
    """A label/value pair; the value can be rendered monospace."""

    def __init__(
        self,
        label: str,
        value: str = "",
        mono: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.label = QLabel(label)
        self.label.setObjectName("Muted")
        self.label.setMinimumWidth(150)
        self.value = QLabel(value)
        self.value.setObjectName("Mono" if mono else "FieldValue")
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.value.setWordWrap(True)
        layout.addWidget(self.label, 0)
        layout.addWidget(self.value, 1)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class StatTile(QWidget):
    """One number with a label underneath."""

    def __init__(
        self, label: str, value: str = "—", parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.label = QLabel(label)
        self.label.setObjectName("StatLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(self.label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class StepRow(QWidget):
    """
    One line of a multi-step outcome.

    Used by the decryption screen to state *exactly* what happened: the
    authentication result, the write result and the restoration result are
    separate rows, so a partially successful run can never be reported as a
    blanket success.
    """

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.label = QLabel(label)
        self.label.setObjectName("FieldLabel")
        self.badge = StatusBadge("pending", "neutral")
        self.badge.setText("—")
        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(self.badge)

    def set_result(self, text: str, variant: str) -> None:
        self.badge.set_status(text, variant)


# ---------------------------------------------------------------------------
# Page furniture.
# ---------------------------------------------------------------------------
class PageHeader(QWidget):
    """Page title, one-line description and optional contextual actions."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(12)
        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.subtitle_label)
        row.addLayout(text_col, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions, 0)
        layout.addLayout(row)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))


class EmptyState(QWidget):
    """
    A friendly "there is nothing here yet" panel with a way forward.

    Used instead of an empty box so a fresh install never looks broken.
    """

    def __init__(
        self,
        icon_name: str,
        title: str,
        message: str = "",
        action_text: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("Faint")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(icons.pixmap(icon_name, "#79839A", 34))
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.message_label = QLabel(message)
        self.message_label.setObjectName("Muted")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(bool(message))
        layout.addWidget(self.message_label)

        self.action: Optional[QPushButton] = None
        if action_text:
            self.action = SecondaryButton(action_text)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(self.action)
            row.addStretch(1)
            layout.addLayout(row)
        layout.addStretch(1)


# ---------------------------------------------------------------------------
# File list.
# ---------------------------------------------------------------------------
class FileList(QWidget):
    """
    Batch file list with drag-and-drop and add/remove controls.

    Emits ``selection_changed(path)`` whenever the current item changes
    ("" when the selection is empty), so the window can show the file in the
    "before" preview the moment it is added — no job required to confirm the
    right image was picked.
    """

    selection_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # -- drop zone -------------------------------------------------------
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.setProperty("dragActive", False)
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(14, 12, 14, 12)
        drop_layout.setSpacing(6)

        drop_text = QLabel("Drop images here")
        drop_text.setObjectName("Muted")
        drop_text.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(drop_text)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.add_btn = SecondaryButton("Add files…")
        self.folder_btn = SecondaryButton("Add folder…")
        self.add_btn.setToolTip("Pick one or more image files for the batch")
        self.folder_btn.setToolTip("Add every image inside a folder")
        self.add_btn.clicked.connect(self._add_dialog)
        self.folder_btn.clicked.connect(self._add_folder)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.folder_btn)
        buttons.addStretch(1)
        drop_layout.addLayout(buttons)
        layout.addWidget(self.drop_zone)

        # -- list ------------------------------------------------------------
        self.listw = QListWidget()
        self.listw.setSelectionMode(QListWidget.ExtendedSelection)
        self.listw.currentItemChanged.connect(self._on_current_changed)
        self.listw.setMinimumHeight(130)
        self.listw.setMaximumHeight(260)
        self.listw.setToolTip(
            "Images to process in one batch — add with the buttons above or "
            "drag & drop anywhere in the window. Clicking an item previews it."
        )
        layout.addWidget(self.listw, 1)

        # -- footer ----------------------------------------------------------
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.count_label = QLabel("No files selected")
        self.count_label.setObjectName("Faint")
        self.clear_btn = GhostButton("Clear")
        self.clear_btn.setToolTip(
            "Remove every file from the list (does not delete anything on disk)"
        )
        self.clear_btn.clicked.connect(self._clear)
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        footer.addWidget(self.clear_btn)
        layout.addLayout(footer)

    # -- data ---------------------------------------------------------------
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
            if path in existing:
                continue
            item = QListWidgetItem(self._label_for(path))
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.listw.addItem(item)
            if first_new is None:
                first_new = item
        self._update_count()
        # Select the newly added file so the preview + info panel update
        # immediately, before any job is started.
        if first_new is not None:
            self.listw.setCurrentItem(first_new)

    def clear(self) -> None:
        self.listw.clear()
        self._update_count()

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _label_for(path: str) -> str:
        name = os.path.basename(path)
        try:
            size = human_size(os.path.getsize(path))
        except OSError:
            return name
        return f"{name}    {size}"

    def _clear(self) -> None:
        self.clear()
        self.selection_changed.emit("")

    def _update_count(self) -> None:
        count = self.listw.count()
        if count == 0:
            self.count_label.setText("No files selected")
        elif count == 1:
            self.count_label.setText("1 file selected")
        else:
            self.count_label.setText(f"{count} files selected")

    def _on_current_changed(self, current, _previous) -> None:
        self.selection_changed.emit(
            current.data(Qt.UserRole) if current is not None else ""
        )

    def _add_dialog(self) -> None:
        from .settings import AppSettings

        settings = AppSettings()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose images", settings.last_dir, IMAGE_FILTER
        )
        if paths:
            settings.last_dir = os.path.dirname(paths[0])
            self.add_paths(paths)

    def _add_folder(self) -> None:
        from .settings import AppSettings

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


# ---------------------------------------------------------------------------
# Previews.
# ---------------------------------------------------------------------------
class PreviewBox(QFrame):
    """
    One image preview (original or result).

    The pixmap is kept at full resolution and re-scaled on resize, so
    dragging the window never degrades the preview permanently.
    """

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Preview")
        self._path: Optional[str] = None
        self._pixmap: Optional[QPixmap] = None
        self._title = title

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        self.path_label = QLabel("")
        self.path_label.setObjectName("Faint")
        self.path_label.setAlignment(Qt.AlignRight)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.path_label)
        layout.addLayout(header)

        self._label = ClickableLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMinimumSize(200, 160)
        self._label.setText("(empty)")
        self._label.setCursor(Qt.PointingHandCursor)
        self._label.setToolTip("Click to enlarge")
        layout.addWidget(self._label, 1)

    # -- state --------------------------------------------------------------
    def set_image(self, path: str) -> bool:
        """Show the image at `path`; returns False when it cannot be read."""
        pix = QPixmap(path)
        if pix.isNull():
            self._label.setText("(cannot load preview)")
            return False
        self._pixmap = pix
        self._path = path
        self._label.setText("")
        self.path_label.setText(os.path.basename(path))
        self.refit()
        return True

    def set_pending(self, text: str = "(pending)") -> None:
        self._label.setPixmap(QPixmap())
        self._label.setText(text)
        self._pixmap = None

    def clear(self) -> None:
        self._label.setPixmap(QPixmap())
        self._label.setText("(empty)")
        self.path_label.setText("")
        self._pixmap = None
        self._path = None

    @property
    def path(self) -> Optional[str]:
        return self._path

    def refit(self) -> None:
        """Re-scale the stored pixmap to the current label size."""
        if self._pixmap is None or self._pixmap.isNull():
            return
        size = self._label.size()
        if size.width() < 4 or size.height() < 4:
            return
        self._label.setPixmap(
            self._pixmap.scaled(
                size * 0.98, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.refit()


class PreviewPanel(QWidget):
    """Before/after previews plus the file metadata panel."""

    def __init__(self, parent=None, show_result: bool = True) -> None:
        super().__init__(parent)
        self.show_result = show_result
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.before = PreviewBox("Original")
        self.after = PreviewBox("Result") if show_result else None
        row.addWidget(self.before, 1)
        if self.after is not None:
            row.addWidget(self.after, 1)
        layout.addLayout(row, 1)

        caption = QLabel(
            "The selected file appears here immediately — click a preview to enlarge"
            if show_result
            else "The selected file appears here immediately — click to enlarge"
        )
        caption.setObjectName("Faint")
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self.info_label = QLabel("")
        self.info_label.setObjectName("Muted")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setVisible(False)
        layout.addWidget(self.info_label)

    def set_info(self, text: str) -> None:
        self.info_label.setText(text)
        self.info_label.setVisible(bool(text))

    def refit(self) -> None:
        self.before.refit()
        if self.after is not None:
            self.after.refit()
