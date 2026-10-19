"""
app.shell
=========

The application shell: a navigation sidebar and a top bar.

These are the two pieces of chrome that frame every page, so they live
together in one module and expose a very small API:

    Sidebar   — wordmark, grouped navigation, device summary
    HeaderBar — contextual actions, theme toggle, settings shortcut

Both are pure presentation. The window owns the navigation state and the
pages; the shell only reports what the user pressed.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import GAP_LG, GAP_MD, GAP_SM, RADIUS_MD, SIDEBAR_WIDTH


class NavButton(QPushButton):
    """A navigation item: icon + label, checkable, keyboard reachable."""

    def __init__(
        self,
        key: str,
        label: str,
        icon_name: str,
        color: str = "#A0A9B8",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(label, parent)
        self.key = key
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self.setIcon(icons.icon(icon_name, color, 18))
        self.setToolTip(f"{label}  (Alt+{_shortcut_digit(key)})")
        self.setAccessibleName(label)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._icon_name = icon_name

    def recolor(self, color: str) -> None:
        self.setIcon(icons.icon(self._icon_name, color, 18))


def _shortcut_digit(key: str) -> int:
    """Alt+<digit> for the first eight navigation items."""
    order = [
        "overview",
        "encrypt",
        "decrypt",
        "verify",
        "analyze",
        "history",
        "settings",
        "about",
    ]
    try:
        return order.index(key) + 1
    except ValueError:
        return 0


class Sidebar(QFrame):
    """
    The navigation sidebar.

    Emits ``navigated(key)`` when an item is activated. The selected item
    is exclusive: activating one releases the others.
    """

    navigated = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._buttons: List[NavButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(GAP_SM)

        # -- brand ------------------------------------------------------------
        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(icons.pixmap("shield", "#38D6A3", 26))
        self.brand_icon.setFixedWidth(26)
        brand.addWidget(self.brand_icon)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        mark = QLabel("OptiCipher")
        mark.setObjectName("BrandMark")
        sub = QLabel("Desktop")
        sub.setObjectName("BrandSub")
        brand_text.addWidget(mark)
        brand_text.addWidget(sub)
        brand.addLayout(brand_text)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(GAP_LG)

        # -- navigation -------------------------------------------------------
        self._sections: List[Tuple[str, List[Tuple[str, str, str]]]] = []

    def add_section(self, title: str, items: List[Tuple[str, str, str]]) -> None:
        """
        Add a group of navigation items.

        `items` is a list of ``(key, label, icon_name)`` tuples.
        """
        if title:
            section = QLabel(title.upper())
            section.setObjectName("NavSection")
            layout = self.layout()
            layout.addWidget(section)
            layout.addSpacing(2)
        for key, label, icon_name in items:
            button = NavButton(key, label, icon_name)
            button.clicked.connect(lambda _checked=False, k=key: self._activate(k))
            self.layout().addWidget(button)
            self._buttons.append(button)
        self.layout().addSpacing(GAP_MD)

    def _activate(self, key: str) -> None:
        self.set_current(key)
        self.navigated.emit(key)

    # -- state --------------------------------------------------------------
    def set_current(self, key: str) -> None:
        """Mark one item as the current page (and release the others)."""
        for button in self._buttons:
            button.setChecked(button.key == key)

    def current_key(self) -> str:
        for button in self._buttons:
            if button.isChecked():
                return button.key
        return ""

    def button(self, key: str) -> Optional[NavButton]:
        for button in self._buttons:
            if button.key == key:
                return button
        return None

    def recolor(self, color: str) -> None:
        for button in self._buttons:
            button.recolor(color)

    # -- footer -------------------------------------------------------------
    def add_footer(self, widget: QWidget) -> None:
        """
        Pin a widget to the bottom of the sidebar (after the navigation).

        Called once the navigation sections have been added, so the footer
        really is the last thing in the column.
        """
        self.layout().addStretch(1)
        self.layout().addWidget(widget)

    def set_device_summary(self, text: str) -> None:
        self.device_label.setText(text)
        self.device_label.setToolTip(
            "Acceleration backend in use (GPU via WebGPU, or CPU fallback) "
            "and its thread settings — click to change it in Settings"
        )


class HeaderBar(QFrame):
    """
    The top bar.

    Left: contextual actions a page may add.
    Right: the theme toggle and the settings shortcut.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self.setFixedHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(GAP_LG, 0, GAP_LG, 0)
        layout.setSpacing(GAP_SM)

        self.left = QHBoxLayout()
        self.left.setSpacing(GAP_SM)
        layout.addLayout(self.left)
        layout.addStretch(1)

        self.right = QHBoxLayout()
        self.right.setSpacing(GAP_SM)
        layout.addLayout(self.right)

    def add_left(self, widget: QWidget) -> None:
        self.left.addWidget(widget)

    def add_right(self, widget: QWidget) -> None:
        self.right.addWidget(widget)
