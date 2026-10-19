"""
app.theme
=========

The design system of OptiCipher Desktop.

Everything visual lives here: the colour tokens, the two palettes (dark is
the default, light is an alternative), the stylesheet generated from a
palette, and the small manager that switches themes at runtime and persists
the choice.

WHY A CENTRAL TOKEN SYSTEM
--------------------------
The old UI sprinkled literal hex strings across a dozen widgets
("color:#888;", "background:#181a20", ...). Changing the accent meant
hunting them down, and the light theme was impossible because there was no
second set of values to switch to.

Here, a colour is defined exactly once — in a :class:`Palette` — and every
widget picks it up through a stylesheet generated from that palette. Adding
a third theme means adding one dataclass, not touching any widget.

The stylesheet is built from ``objectName`` selectors (``QPushButton#Primary``,
``QFrame#Card``, ...), so components declare their role once and inherit the
whole visual system. That keeps the widget code free of inline stylesheets.

The palette also drives Qt's own ``QPalette`` so that the parts of Qt we do
not style ourselves (popups, menus, spin boxes, native scroll areas) still
look right in both themes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# ---------------------------------------------------------------------------
# Geometry tokens — one place for every radius / spacing value.
# ---------------------------------------------------------------------------
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12

GAP_XS = 4
GAP_SM = 8
GAP_MD = 12
GAP_LG = 16
GAP_XL = 24

SIDEBAR_WIDTH = 232
MIN_WINDOW_WIDTH = 960
MIN_WINDOW_HEIGHT = 620


# ---------------------------------------------------------------------------
# Palettes.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Palette:
    """One complete set of colour tokens."""

    name: str

    # Surfaces
    bg: str              # window background
    surface: str         # cards / panels
    surface_alt: str     # sidebar, inputs, wells
    surface_hover: str   # hovered input / row
    overlay: str         # scrim behind dialogs

    # Lines
    border: str
    border_strong: str

    # Type
    text: str
    text_dim: str
    text_faint: str
    text_on_accent: str

    # Brand
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str     # translucent accent for selected rows

    # Status
    danger: str
    danger_soft: str
    warning: str
    warning_soft: str
    success: str
    success_soft: str
    info: str
    info_soft: str


DARK = Palette(
    name="dark",
    bg="#101318",
    surface="#1B202A",
    surface_alt="#151922",
    surface_hover="#232A36",
    overlay="#0A0C10",
    border="#2B3240",
    border_strong="#3A4354",
    text="#F1F4F8",
    text_dim="#A0A9B8",
    text_faint="#79839A",
    text_on_accent="#062018",
    accent="#38D6A3",
    accent_hover="#4FE3B4",
    accent_pressed="#2BB88C",
    accent_soft="#1C3A31",
    danger="#F2686D",
    danger_soft="#3A1F22",
    warning="#F0B429",
    warning_soft="#3A2F14",
    success="#46D68A",
    success_soft="#15321F",
    info="#6BB0FF",
    info_soft="#16273D",
)

LIGHT = Palette(
    name="light",
    bg="#F4F6F9",
    surface="#FFFFFF",
    surface_alt="#EDF1F6",
    surface_hover="#E2E8F0",
    overlay="#5A6472",
    border="#D8DEE8",
    border_strong="#BFC8D6",
    text="#131820",
    text_dim="#56616F",
    text_faint="#7A8595",
    text_on_accent="#FFFFFF",
    accent="#0A7D5C",
    accent_hover="#096E50",
    accent_pressed="#075E44",
    accent_soft="#D6EFE6",
    danger="#C62F35",
    danger_soft="#FBE9EA",
    warning="#8A5D00",
    warning_soft="#FDF3DC",
    success="#12805C",
    success_soft="#E2F5EC",
    info="#2563C9",
    info_soft="#E6EFFC",
)

PALETTES = {"dark": DARK, "light": LIGHT}
DEFAULT_THEME = "dark"


def palette(name: str) -> Palette:
    """The palette for `name` (falls back to the default theme)."""
    return PALETTES.get(name, PALETTES[DEFAULT_THEME])


# ---------------------------------------------------------------------------
# Qt palette (the parts of Qt we do not style ourselves).
# ---------------------------------------------------------------------------
def qt_palette(p: Palette) -> QPalette:
    """Build a Qt palette matching the design tokens."""
    qp = QPalette()
    qp.setColor(QPalette.Window, QColor(p.bg))
    qp.setColor(QPalette.WindowText, QColor(p.text))
    qp.setColor(QPalette.Base, QColor(p.surface_alt))
    qp.setColor(QPalette.AlternateBase, QColor(p.surface))
    qp.setColor(QPalette.ToolTipBase, QColor(p.surface))
    qp.setColor(QPalette.ToolTipText, QColor(p.text))
    qp.setColor(QPalette.Text, QColor(p.text))
    qp.setColor(QPalette.Button, QColor(p.surface_alt))
    qp.setColor(QPalette.ButtonText, QColor(p.text))
    qp.setColor(QPalette.BrightText, QColor(p.danger))
    qp.setColor(QPalette.Link, QColor(p.accent))
    qp.setColor(QPalette.LinkVisited, QColor(p.accent_hover))
    qp.setColor(QPalette.Highlight, QColor(p.accent))
    qp.setColor(QPalette.HighlightedText, QColor(p.text_on_accent))
    qp.setColor(QPalette.PlaceholderText, QColor(p.text_faint))
    qp.setColor(QPalette.Disabled, QPalette.Text, QColor(p.text_faint))
    qp.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p.text_faint))
    qp.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p.text_faint))
    return qp


def mono_font(size: int = 10) -> QFont:
    """The platform's fixed-width font, for hashes and technical values."""
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setPointSize(size)
    return font


# ---------------------------------------------------------------------------
# Stylesheet.
# ---------------------------------------------------------------------------
def build_stylesheet(p: Palette) -> str:
    """
    The application stylesheet for one palette.

    Every rule is keyed on a role (objectName), never on a concrete widget
    class, so a component can be restyled by changing its role — and the
    whole look changes by swapping the palette.
    """
    return f"""
/* ---------- base ---------- */
QWidget {{
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
}}
QMainWindow, QDialog {{
    background-color: {p.bg};
}}
QToolTip {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_SM}px;
    padding: 6px 8px;
}}

/* ---------- text roles ---------- */
QLabel#PageTitle {{
    font-size: 21px;
    font-weight: 600;
    color: {p.text};
}}
QLabel#PageSubtitle {{
    font-size: 13px;
    color: {p.text_dim};
}}
QLabel#SectionTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {p.text};
}}
QLabel#Muted {{
    color: {p.text_dim};
}}
QLabel#Faint {{
    color: {p.text_faint};
}}
QLabel#FieldLabel {{
    color: {p.text_dim};
    font-size: 12px;
}}
QLabel#FieldValue {{
    color: {p.text};
}}
QLabel#ErrorText {{
    color: {p.danger};
}}
QLabel#SuccessText {{
    color: {p.success};
}}
QLabel#WarningText {{
    color: {p.warning};
}}
QLabel#HeroTitle {{
    font-size: 26px;
    font-weight: 600;
    color: {p.text};
}}
QLabel#HeroText {{
    font-size: 14px;
    color: {p.text_dim};
}}
QLabel#BrandMark {{
    font-size: 16px;
    font-weight: 600;
    color: {p.text};
}}
QLabel#BrandSub {{
    font-size: 11px;
    color: {p.text_faint};
}}
QLabel#NavSection {{
    font-size: 10px;
    font-weight: 600;
    color: {p.text_faint};
    letter-spacing: 1px;
}}
QLabel#StatValue {{
    font-size: 20px;
    font-weight: 600;
    color: {p.text};
}}
QLabel#StatLabel {{
    font-size: 11px;
    color: {p.text_faint};
}}
QLabel#Mono {{
    color: {p.text_dim};
}}
QLabel#BadgeSuccess {{
    color: {p.success};
    background-color: {p.success_soft};
    border: 1px solid {p.success};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#BadgeError {{
    color: {p.danger};
    background-color: {p.danger_soft};
    border: 1px solid {p.danger};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#BadgeWarning {{
    color: {p.warning};
    background-color: {p.warning_soft};
    border: 1px solid {p.warning};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#BadgeInfo {{
    color: {p.info};
    background-color: {p.info_soft};
    border: 1px solid {p.info};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#BadgeNeutral {{
    color: {p.text_dim};
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}

/* ---------- surfaces ---------- */
QFrame#Card {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_LG}px;
}}
QFrame#CardFlat {{
    background-color: {p.surface};
    border: none;
    border-radius: {RADIUS_LG}px;
}}
QFrame#Divider {{
    background-color: {p.border};
    max-height: 1px;
    border: none;
}}
QFrame#VDivider {{
    background-color: {p.border};
    max-width: 1px;
    border: none;
}}
QFrame#Sidebar {{
    background-color: {p.surface_alt};
    border-right: 1px solid {p.border};
}}
QFrame#HeaderBar {{
    background-color: {p.bg};
    border-bottom: 1px solid {p.border};
}}
QFrame#Well {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
}}
QFrame#AccentWell {{
    background-color: {p.accent_soft};
    border: 1px solid {p.accent};
    border-radius: {RADIUS_MD}px;
}}
QFrame#DropZone {{
    background-color: {p.surface_alt};
    border: 1px dashed {p.border_strong};
    border-radius: {RADIUS_LG}px;
}}
QFrame#DropZone[dragActive="true"] {{
    border: 1px solid {p.accent};
    background-color: {p.accent_soft};
}}
QFrame#Preview {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
}}
QFrame#StatusStrip {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {p.surface_hover};
    border-color: {p.border_strong};
}}
QPushButton:pressed {{
    background-color: {p.border};
}}
QPushButton:focus {{
    border-color: {p.accent};
}}
QPushButton:disabled {{
    color: {p.text_faint};
    background-color: {p.surface_alt};
    border-color: {p.border};
}}
QPushButton#Primary {{
    background-color: {p.accent};
    color: {p.text_on_accent};
    border: 1px solid {p.accent};
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background-color: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton#Primary:pressed {{
    background-color: {p.accent_pressed};
    border-color: {p.accent_pressed};
}}
QPushButton#Primary:disabled {{
    background-color: {p.surface_alt};
    color: {p.text_faint};
    border-color: {p.border};
}}
QPushButton#Danger {{
    background-color: {p.danger};
    color: #ffffff;
    border: 1px solid {p.danger};
    font-weight: 600;
}}
QPushButton#Danger:hover {{
    background-color: {p.danger};
    border-color: {p.danger};
}}
QPushButton#Ghost {{
    background: transparent;
    border: 1px solid transparent;
    color: {p.text_dim};
    padding: 6px 10px;
}}
QPushButton#Ghost:hover {{
    background-color: {p.surface_hover};
    color: {p.text};
}}
QPushButton#Ghost:disabled {{
    color: {p.text_faint};
    background: transparent;
}}
QPushButton#IconButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_MD}px;
    padding: 6px;
}}
QPushButton#IconButton:hover {{
    background-color: {p.surface_hover};
}}
QPushButton#IconButton:pressed {{
    background-color: {p.border};
}}
QPushButton#IconButton:focus {{
    border-color: {p.accent};
}}
QPushButton#NavButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_MD}px;
    padding: 9px 12px;
    text-align: left;
    color: {p.text_dim};
    font-size: 13px;
}}
QPushButton#NavButton:hover {{
    background-color: {p.surface_hover};
    color: {p.text};
}}
QPushButton#NavButton:checked {{
    background-color: {p.accent_soft};
    color: {p.text};
    font-weight: 600;
}}
QPushButton#NavButton:focus {{
    border-color: {p.accent};
}}
QPushButton#QuickAction {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS_LG}px;
    padding: 14px 16px;
    text-align: left;
    font-size: 13px;
}}
QPushButton#QuickAction:hover {{
    background-color: {p.surface_hover};
    border-color: {p.accent};
}}
QPushButton#QuickAction:focus {{
    border-color: {p.accent};
}}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: 7px 10px;
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {p.text_faint};
    background-color: {p.surface};
}}
QLineEdit[readOnly="true"] {{
    color: {p.text_dim};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_MD}px;
    padding: 4px;
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {p.surface_hover};
    border-radius: 3px;
}}
QCheckBox, QRadioButton {{
    color: {p.text};
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.border_strong};
    background-color: {p.surface_alt};
}}
QCheckBox::indicator {{
    border-radius: 4px;
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}

/* ---------- lists, tables, trees ---------- */
QListWidget, QTableWidget, QTreeWidget, QTreeView, QTableView {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    outline: none;
}}
QListWidget::item {{
    padding: 7px 8px;
    border-radius: {RADIUS_SM}px;
    color: {p.text};
}}
QListWidget::item:hover {{
    background-color: {p.surface_hover};
}}
QListWidget::item:selected {{
    background-color: {p.accent_soft};
    color: {p.text};
}}
QHeaderView::section {{
    background-color: {p.surface};
    color: {p.text_dim};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 7px 8px;
    font-size: 12px;
}}
QTableWidget {{ gridline-color: {p.border}; }}
QTableWidget::item:selected {{
    background-color: {p.accent_soft};
    color: {p.text};
}}

/* ---------- progress ---------- */
QProgressBar {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS_SM}px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {p.accent};
    border-radius: {RADIUS_SM}px;
}}

/* ---------- slider ---------- */
QSlider::groove:horizontal {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    height: 6px;
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background-color: {p.accent};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background-color: {p.text};
    border: 2px solid {p.accent};
    width: 14px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background-color: {p.accent_hover};
}}

/* ---------- status bar & menus ---------- */
QStatusBar {{
    background-color: {p.surface_alt};
    color: {p.text_dim};
    border-top: 1px solid {p.border};
}}
QStatusBar::item {{ border: none; }}
QMenuBar {{
    background-color: {p.bg};
    color: {p.text_dim};
    border-bottom: 1px solid {p.border};
}}
QMenuBar::item:selected {{
    background-color: {p.surface_hover};
    color: {p.text};
}}
QMenu {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_MD}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 24px 7px 12px;
    border-radius: {RADIUS_SM}px;
}}
QMenu::item:selected {{
    background-color: {p.accent_soft};
    color: {p.text};
}}
QMenu::separator {{
    height: 1px;
    background: {p.border};
    margin: 6px 8px;
}}

/* ---------- message box ---------- */
QMessageBox {{
    background-color: {p.bg};
}}
QMessageBox QLabel {{
    color: {p.text};
}}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- misc ---------- */
QSplitter::handle {{
    background-color: {p.border};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QToolButton {{
    color: {p.text_dim};
    border: none;
}}
QToolButton:hover {{ color: {p.text}; }}
"""


# ---------------------------------------------------------------------------
# Theme manager.
# ---------------------------------------------------------------------------
class ThemeManager(QObject):
    """
    Owns the active theme, applies it to the application, and remembers it.

    The preference lives in ``QSettings`` (see :mod:`app.settings`), so the
    choice survives a restart. Applying a theme rewrites the application
    stylesheet and the Qt palette in one go — there is no partially themed
    state, and no white flash, because the palette is set *before* the
    stylesheet and both happen inside a single event-loop-free call.
    """

    theme_changed = Signal(str)

    def __init__(self, settings=None, parent=None) -> None:
        super().__init__(parent)
        if settings is None:
            from .settings import AppSettings

            settings = AppSettings()
        self._settings = settings
        self._name = self._settings.theme if self._settings.theme in PALETTES else DEFAULT_THEME

    # -- state --------------------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def palette(self) -> Palette:
        return palette(self._name)

    @property
    def is_dark(self) -> bool:
        return self._name == "dark"

    # -- actions ------------------------------------------------------------
    def set_theme(self, name: str) -> None:
        """Switch to `name` ("dark" / "light"); unknown names are ignored."""
        if name not in PALETTES or name == self._name:
            return
        self._name = name
        self._settings.theme = name
        self.apply()
        self.theme_changed.emit(name)

    def toggle(self) -> str:
        """Flip between the two themes and return the new name."""
        self.set_theme("light" if self._name == "dark" else "dark")
        return self._name

    def apply(self, app: Optional[QApplication] = None) -> None:
        """
        Apply the current theme to the application (and any widget).

        Re-applying an identical stylesheet would make Qt re-style every
        live widget in the process, so an unchanged theme is a no-op.
        """
        app = app or QApplication.instance()
        if app is None:
            return
        p = self.palette
        sheet = build_stylesheet(p)
        if app.styleSheet() == sheet:
            return
        app.setPalette(qt_palette(p))
        app.setStyleSheet(sheet)


def style_widget(widget: QWidget, palette_obj: Optional[Palette] = None) -> None:
    """
    Apply the palette to a single widget.

    Only needed for widgets that live outside a ``QApplication`` stylesheet
    scope (rare); the global stylesheet normally covers everything.
    """
    if palette_obj is not None:
        widget.setPalette(qt_palette(palette_obj))


# Re-exported so callers can do `from app.theme import Qt` style checks.
__all__ = [
    "DARK",
    "LIGHT",
    "PALETTES",
    "DEFAULT_THEME",
    "Palette",
    "ThemeManager",
    "build_stylesheet",
    "mono_font",
    "palette",
    "qt_palette",
    "RADIUS_SM",
    "RADIUS_MD",
    "RADIUS_LG",
    "GAP_XS",
    "GAP_SM",
    "GAP_MD",
    "GAP_LG",
    "GAP_XL",
    "SIDEBAR_WIDTH",
    "MIN_WINDOW_WIDTH",
    "MIN_WINDOW_HEIGHT",
    "Qt",
]
