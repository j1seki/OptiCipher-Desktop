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


class HistogramBars(QWidget):
    """A 256-bin histogram; bars scaled to the max bin (sqrt scale keeps
    small bins visible next to dominant ones without lying about shape)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._counts: Sequence[int] = []
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_counts(self, counts: Sequence[int]) -> None:
        self._counts = list(counts)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.fillRect(rect, QColor(24, 26, 32))
        if not self._counts or max(self._counts) == 0:
            painter.end()
            return
        import math

        peak = math.sqrt(max(self._counts))
        bar_w = rect.width() / 256.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(90, 170, 255))
        for i, value in enumerate(self._counts[:256]):
            if value == 0:
                continue
            h = math.sqrt(value) / peak * rect.height()
            x = rect.x() + i * bar_w
            painter.drawRect(
                int(x), int(rect.bottom() - h) + 1, max(1, int(bar_w)), int(h)
            )
        painter.setPen(QPen(QColor(70, 74, 84)))
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
        painter.setPen(QColor(210, 214, 222))
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
        painter.fillRect(track, QColor(38, 41, 49))
        if self.ideal:
            lo, hi = self.ideal
            band = track.adjusted(
                int(track.width() * lo / self.maximum), 0,
                -int(track.width() * (1 - hi / self.maximum)), 0,
            )
            painter.fillRect(band, QColor(70, 120, 90, 90))
        if self.value is not None:
            frac = max(0.0, min(1.0, self.value / self.maximum))
            fill = track.adjusted(0, 0, -int(track.width() * (1 - frac)), 0)
            painter.fillRect(fill, QColor(90, 170, 255))
        painter.setPen(QPen(QColor(70, 74, 84)))
        painter.drawRect(track)
        painter.end()
