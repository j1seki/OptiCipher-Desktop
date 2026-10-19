"""
app.charts
==========

Small self-contained chart widgets (no plotting-library dependency):

  * HistogramBars — 256-bin channel histogram with log-ish scaling, drawn
    with QPainter. Used by the Analyze tab to eyeball diffusion quality
    (flat histogram = good ciphertext).
  * ValueBar      — a labelled horizontal bar for a metric with an optional
    ideal-range band (e.g. entropy target ~8.0, NPCR target ~99.6%).
"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

#: Per-channel bar colours for the Analyze histogram (image-editor
#: convention). Keyed by the histogram dict keys built in app.workers.
CHANNEL_COLORS = {
    "channel_0": QColor(244, 95, 95),  # red
    "channel_1": QColor(96, 214, 120),  # green
    "channel_2": QColor(90, 170, 255),  # blue (the historic default)
    "channel_3": QColor(240, 196, 84),  # alpha, amber
}

#: Friendly combo labels for the same keys.
CHANNEL_LABELS = {
    "channel_0": "Red (channel 0)",
    "channel_1": "Green (channel 1)",
    "channel_2": "Blue (channel 2)",
    "channel_3": "Alpha (channel 3)",
}

#: Colours the chart widgets paint with. Seeded with the dark palette and
#: refreshed by :func:`set_theme_colors` whenever the theme changes, so the
#: charts follow the rest of the application instead of staying dark in a
#: light window.
_THEME = {
    "panel": "#151922",
    "border": "#2B3240",
    "track": "#1B202A",
    "text": "#F1F4F8",
    "fill": "#38D6A3",
    "ideal": "#46D68A",
}


def set_theme_colors(palette) -> None:
    """Point the chart colours at the active design palette."""
    _THEME["panel"] = palette.surface_alt
    _THEME["border"] = palette.border
    _THEME["track"] = palette.surface
    _THEME["text"] = palette.text
    _THEME["fill"] = palette.accent
    _THEME["ideal"] = palette.success


class HistogramBars(QWidget):
    """A 256-bin histogram; bars scaled to the max bin (sqrt scale keeps
    small bins visible next to dominant ones without lying about shape).

    The bar colour follows the displayed channel (image-editor convention:
    red/green/blue per RGB channel) so a glance says *which* channel is
    shown without reading the combo box.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._counts: Sequence[int] = []
        self._color = QColor(90, 170, 255)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_counts(
        self, counts: Sequence[int], key: Optional[str] = None
    ) -> None:
        """Show `counts`; `key` (e.g. 'channel_1') picks the bar colour."""
        self._counts = list(counts)
        self._color = CHANNEL_COLORS.get(key or "", QColor(90, 170, 255))
        self.update()

    @property
    def bar_color(self) -> QColor:
        return QColor(self._color)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.fillRect(rect, QColor(_THEME["panel"]))
        if not self._counts or max(self._counts) == 0:
            painter.end()
            return
        import math

        peak = math.sqrt(max(self._counts))
        bar_w = rect.width() / 256.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        for i, value in enumerate(self._counts[:256]):
            if value == 0:
                continue
            h = math.sqrt(value) / peak * rect.height()
            x = rect.x() + i * bar_w
            painter.drawRect(
                int(x), int(rect.bottom() - h) + 1, max(1, int(bar_w)), int(h)
            )
        painter.setPen(QPen(QColor(_THEME["border"])))
        painter.drawRect(rect)
        painter.end()


class ValueBar(QWidget):
    """Horizontal metric bar; `ideal` draws a translucent target band."""

    def __init__(self, label: str, maximum: float = 100.0, ideal: Optional[tuple] = None, parent=None) -> None:
        super().__init__(parent)
        self.label = label
        self.maximum = maximum
        self.ideal = ideal
        self.value: Optional[float] = None
        self.setMinimumHeight(26)

    def set_value(self, value: Optional[float]) -> None:
        self.value = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect()
        text_rect = rect.adjusted(8, 0, -8, 0)
        painter.setPen(QColor(_THEME["text"]))
        painter.drawText(
            text_rect, Qt.AlignVCenter | Qt.AlignLeft, f"{self.label}"
        )
        if self.value is not None:
            painter.drawText(
                text_rect,
                Qt.AlignVCenter | Qt.AlignRight,
                f"{self.value:.4g}",
            )
        # track
        track = rect.adjusted(150, 6, -60, -6)
        painter.fillRect(track, QColor(_THEME["track"]))
        if self.ideal:
            lo, hi = self.ideal
            band = track.adjusted(
                int(track.width() * lo / self.maximum), 0,
                -int(track.width() * (1 - hi / self.maximum)), 0,
            )
            painter.fillRect(band, QColor(_THEME["ideal"]))
        if self.value is not None:
            frac = max(0.0, min(1.0, self.value / self.maximum))
            fill = track.adjusted(0, 0, -int(track.width() * (1 - frac)), 0)
            painter.fillRect(fill, QColor(_THEME["fill"]))
        painter.setPen(QPen(QColor(_THEME["border"])))
        painter.drawRect(track)
        painter.end()
