"""
app.icons
=========

A tiny, dependency-free vector icon set.

Why not an icon package?
------------------------
Every icon-pack dependency (Font Awesome, QtAwesome, Lucide, …) is another
package to vendor into the PyInstaller bundle, another licence to track, and
another thing that can render at the wrong weight in a dark theme. The
application needs about two dozen glyphs, so they are drawn here with
``QPainter``: crisp at any DPI, recoloured per theme, and zero dependencies.

Every glyph is stroked (never filled) with a round cap, which gives the whole
set one consistent weight and optical size.

Usage
-----
    button.setIcon(app.icons.icon("lock", theme.palette.text_dim))
    label.setPixmap(app.icons.pixmap("shield", theme.palette.accent, 32))
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

#: Stroke width as a fraction of the icon size — keeps the optical weight
#: identical whatever size the icon is drawn at.
_STROKE_RATIO = 0.085

_Drawer = Callable[[QPainter, QRectF, QColor], None]


def _pen(painter: QPainter, color: QColor, size: int) -> QPen:
    pen = QPen(color)
    pen.setWidthF(max(1.0, size * _STROKE_RATIO))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    return pen


def _r(p: QRectF, x: float, y: float, w: float, h: float) -> QRectF:
    """A rectangle expressed in 0..1 units of the icon box."""
    return QRectF(p.x() + p.width() * x, p.y() + p.height() * y,
                  p.width() * w, p.height() * h)


# ---------------------------------------------------------------------------
# Glyphs.
# ---------------------------------------------------------------------------
def _shield(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.center().x(), box.top())
    path.lineTo(box.right(), box.top() + box.height() * 0.22)
    path.lineTo(box.right(), box.center().y())
    path.quadTo(box.right(), box.bottom(), box.center().x(), box.bottom())
    path.quadTo(box.left(), box.bottom(), box.left(), box.center().y())
    path.lineTo(box.left(), box.top() + box.height() * 0.22)
    path.closeSubpath()
    p.drawPath(path)


def _lock(p: QPainter, box: QRectF, c: QColor) -> None:
    body = _r(box, 0.20, 0.44, 0.60, 0.44)
    p.drawRoundedRect(body, body.width() * 0.18, body.width() * 0.18)
    shackle = QPainterPath()
    shackle.moveTo(box.x() + box.width() * 0.34, box.y() + box.height() * 0.44)
    shackle.lineTo(box.x() + box.width() * 0.34, box.y() + box.height() * 0.30)
    shackle.arcTo(
        QRectF(box.x() + box.width() * 0.34, box.y() + box.height() * 0.12,
               box.width() * 0.32, box.height() * 0.36),
        180, -180,
    )
    shackle.lineTo(box.x() + box.width() * 0.66, box.y() + box.height() * 0.44)
    p.drawPath(shackle)


def _unlock(p: QPainter, box: QRectF, c: QColor) -> None:
    body = _r(box, 0.20, 0.44, 0.60, 0.44)
    p.drawRoundedRect(body, body.width() * 0.18, body.width() * 0.18)
    shackle = QPainterPath()
    shackle.moveTo(box.x() + box.width() * 0.34, box.y() + box.height() * 0.44)
    shackle.lineTo(box.x() + box.width() * 0.34, box.y() + box.height() * 0.30)
    shackle.arcTo(
        QRectF(box.x() + box.width() * 0.34, box.y() + box.height() * 0.12,
               box.width() * 0.32, box.height() * 0.36),
        180, -180,
    )
    shackle.lineTo(box.x() + box.width() * 0.66, box.y() + box.height() * 0.30)
    p.drawPath(shackle)


def _check(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.x() + box.width() * 0.20, box.y() + box.height() * 0.52)
    path.lineTo(box.x() + box.width() * 0.42, box.y() + box.height() * 0.74)
    path.lineTo(box.x() + box.width() * 0.80, box.y() + box.height() * 0.28)
    p.drawPath(path)


def _cross(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawLine(
        QPointF(box.x() + box.width() * 0.26, box.y() + box.height() * 0.26),
        QPointF(box.x() + box.width() * 0.74, box.y() + box.height() * 0.74),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.74, box.y() + box.height() * 0.26),
        QPointF(box.x() + box.width() * 0.26, box.y() + box.height() * 0.74),
    )


def _alert(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.center().x(), box.top() + box.height() * 0.08)
    path.lineTo(box.right() - box.width() * 0.06, box.bottom() - box.height() * 0.12)
    path.lineTo(box.left() + box.width() * 0.06, box.bottom() - box.height() * 0.12)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(
        QPointF(box.center().x(), box.y() + box.height() * 0.40),
        QPointF(box.center().x(), box.y() + box.height() * 0.66),
    )
    p.drawPoint(QPointF(box.center().x(), box.y() + box.height() * 0.78))


def _info(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawEllipse(box.adjusted(box.width() * 0.06, box.height() * 0.06,
                               -box.width() * 0.06, -box.height() * 0.06))
    p.drawLine(
        QPointF(box.center().x(), box.y() + box.height() * 0.44),
        QPointF(box.center().x(), box.y() + box.height() * 0.72),
    )
    p.drawPoint(QPointF(box.center().x(), box.y() + box.height() * 0.32))


def _chart(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawLine(
        QPointF(box.x() + box.width() * 0.16, box.y() + box.height() * 0.16),
        QPointF(box.x() + box.width() * 0.16, box.y() + box.height() * 0.84),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.16, box.y() + box.height() * 0.84),
        QPointF(box.x() + box.width() * 0.86, box.y() + box.height() * 0.84),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.32, box.y() + box.height() * 0.66),
        QPointF(box.x() + box.width() * 0.32, box.y() + box.height() * 0.84),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.50, box.y() + box.height() * 0.48),
        QPointF(box.x() + box.width() * 0.50, box.y() + box.height() * 0.84),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.68, box.y() + box.height() * 0.30),
        QPointF(box.x() + box.width() * 0.68, box.y() + box.height() * 0.84),
    )


def _clock(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawEllipse(box.adjusted(box.width() * 0.08, box.height() * 0.08,
                               -box.width() * 0.08, -box.height() * 0.08))
    p.drawLine(
        QPointF(box.center().x(), box.center().y()),
        QPointF(box.center().x(), box.y() + box.height() * 0.28),
    )
    p.drawLine(
        QPointF(box.center().x(), box.center().y()),
        QPointF(box.x() + box.width() * 0.70, box.y() + box.height() * 0.58),
    )


def _gear(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawEllipse(box.adjusted(box.width() * 0.30, box.height() * 0.30,
                               -box.width() * 0.30, -box.height() * 0.30))
    for i in range(8):
        angle = math.radians(i * 45)
        inner = box.width() * 0.20
        outer = box.width() * 0.34
        cx, cy = box.center().x(), box.center().y()
        p.drawLine(
            QPointF(cx + inner * math.cos(angle), cy + inner * math.sin(angle)),
            QPointF(cx + outer * math.cos(angle), cy + outer * math.sin(angle)),
        )


def _folder(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.left() + box.width() * 0.10, box.top() + box.height() * 0.74)
    path.lineTo(box.left() + box.width() * 0.10, box.top() + box.height() * 0.24)
    path.lineTo(box.left() + box.width() * 0.40, box.top() + box.height() * 0.24)
    path.lineTo(box.left() + box.width() * 0.48, box.top() + box.height() * 0.36)
    path.lineTo(box.right() - box.width() * 0.10, box.top() + box.height() * 0.36)
    path.lineTo(box.right() - box.width() * 0.10, box.top() + box.height() * 0.74)
    path.closeSubpath()
    p.drawPath(path)


def _file(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.left() + box.width() * 0.20, box.top() + box.height() * 0.10)
    path.lineTo(box.left() + box.width() * 0.58, box.top() + box.height() * 0.10)
    path.lineTo(box.right() - box.width() * 0.18, box.top() + box.height() * 0.32)
    path.lineTo(box.right() - box.width() * 0.18, box.bottom() - box.height() * 0.10)
    path.lineTo(box.left() + box.width() * 0.20, box.bottom() - box.height() * 0.10)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(
        QPointF(box.left() + box.width() * 0.58, box.top() + box.height() * 0.10),
        QPointF(box.left() + box.width() * 0.58, box.top() + box.height() * 0.32),
    )
    p.drawLine(
        QPointF(box.left() + box.width() * 0.58, box.top() + box.height() * 0.32),
        QPointF(box.right() - box.width() * 0.18, box.top() + box.height() * 0.32),
    )


def _plus(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawLine(
        QPointF(box.center().x(), box.y() + box.height() * 0.22),
        QPointF(box.center().x(), box.y() + box.height() * 0.78),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.22, box.center().y()),
        QPointF(box.x() + box.width() * 0.78, box.center().y()),
    )


def _trash(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawLine(
        QPointF(box.x() + box.width() * 0.16, box.y() + box.height() * 0.28),
        QPointF(box.x() + box.width() * 0.84, box.y() + box.height() * 0.28),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.38, box.y() + box.height() * 0.20),
        QPointF(box.x() + box.width() * 0.62, box.y() + box.height() * 0.20),
    )
    body = _r(box, 0.24, 0.28, 0.52, 0.58)
    p.drawRoundedRect(body, body.width() * 0.14, body.width() * 0.14)
    p.drawLine(
        QPointF(box.x() + box.width() * 0.42, box.y() + box.height() * 0.42),
        QPointF(box.x() + box.width() * 0.42, box.y() + box.height() * 0.74),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.58, box.y() + box.height() * 0.42),
        QPointF(box.x() + box.width() * 0.58, box.y() + box.height() * 0.74),
    )


def _play(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.x() + box.width() * 0.28, box.y() + box.height() * 0.18)
    path.lineTo(box.x() + box.width() * 0.80, box.center().y())
    path.lineTo(box.x() + box.width() * 0.28, box.bottom() - box.height() * 0.18)
    path.closeSubpath()
    p.drawPath(path)


def _stop(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawRoundedRect(_r(box, 0.24, 0.24, 0.52, 0.52), 4, 4)


def _sun(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawEllipse(box.adjusted(box.width() * 0.28, box.height() * 0.28,
                               -box.width() * 0.28, -box.height() * 0.28))
    for i in range(8):
        angle = math.radians(i * 45)
        cx, cy = box.center().x(), box.center().y()
        r0 = box.width() * 0.40
        r1 = box.width() * 0.50
        p.drawLine(
            QPointF(cx + r0 * math.cos(angle), cy + r0 * math.sin(angle)),
            QPointF(cx + r1 * math.cos(angle), cy + r1 * math.sin(angle)),
        )


def _moon(p: QPainter, box: QRectF, c: QColor) -> None:
    # A filled crescent: the outer arc of a circle plus the inner arc of an
    # offset circle, closed into one path. Filled (not stroked) so it stays
    # legible at 16-18 px.
    outer = box.adjusted(box.width() * 0.14, box.height() * 0.14,
                         -box.width() * 0.14, -box.height() * 0.14)
    inner = QRectF(
        outer.x() + outer.width() * 0.42,
        outer.y() - outer.height() * 0.18,
        outer.width() * 0.95,
        outer.height() * 0.95,
    )
    path = QPainterPath()
    path.arcMoveTo(outer, 62)
    path.arcTo(outer, 62, 236)
    path.arcTo(inner, 300, -236)
    path.closeSubpath()
    p.setBrush(c)
    p.drawPath(path)
    p.setBrush(Qt.NoBrush)


def _upload(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawLine(
        QPointF(box.center().x(), box.y() + box.height() * 0.70),
        QPointF(box.center().x(), box.y() + box.height() * 0.18),
    )
    p.drawLine(
        QPointF(box.center().x() - box.width() * 0.16, box.y() + box.height() * 0.34),
        QPointF(box.center().x(), box.y() + box.height() * 0.18),
    )
    p.drawLine(
        QPointF(box.center().x() + box.width() * 0.16, box.y() + box.height() * 0.34),
        QPointF(box.center().x(), box.y() + box.height() * 0.18),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.16, box.y() + box.height() * 0.62),
        QPointF(box.x() + box.width() * 0.16, box.y() + box.height() * 0.86),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.84, box.y() + box.height() * 0.62),
        QPointF(box.x() + box.width() * 0.84, box.y() + box.height() * 0.86),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.16, box.y() + box.height() * 0.86),
        QPointF(box.x() + box.width() * 0.84, box.y() + box.height() * 0.86),
    )


def _key(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawEllipse(_r(box, 0.08, 0.28, 0.32, 0.32))
    p.drawLine(
        QPointF(box.x() + box.width() * 0.38, box.y() + box.height() * 0.56),
        QPointF(box.right() - box.width() * 0.12, box.y() + box.height() * 0.76),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.66, box.y() + box.height() * 0.68),
        QPointF(box.x() + box.width() * 0.74, box.y() + box.height() * 0.56),
    )


def _image(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawRoundedRect(_r(box, 0.10, 0.16, 0.80, 0.68), 5, 5)
    p.drawEllipse(_r(box, 0.28, 0.28, 0.14, 0.14))
    path = QPainterPath()
    path.moveTo(box.x() + box.width() * 0.14, box.y() + box.height() * 0.78)
    path.lineTo(box.x() + box.width() * 0.38, box.y() + box.height() * 0.50)
    path.lineTo(box.x() + box.width() * 0.56, box.y() + box.height() * 0.70)
    path.lineTo(box.x() + box.width() * 0.68, box.y() + box.height() * 0.56)
    path.lineTo(box.x() + box.width() * 0.86, box.y() + box.height() * 0.78)
    p.drawPath(path)


def _pulse(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.x() + box.width() * 0.08, box.center().y())
    path.lineTo(box.x() + box.width() * 0.28, box.center().y())
    path.lineTo(box.x() + box.width() * 0.40, box.y() + box.height() * 0.24)
    path.lineTo(box.x() + box.width() * 0.56, box.y() + box.height() * 0.76)
    path.lineTo(box.x() + box.width() * 0.68, box.center().y())
    path.lineTo(box.x() + box.width() * 0.92, box.center().y())
    p.drawPath(path)


def _arrow_right(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawLine(
        QPointF(box.x() + box.width() * 0.16, box.center().y()),
        QPointF(box.x() + box.width() * 0.82, box.center().y()),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.58, box.y() + box.height() * 0.26),
        QPointF(box.x() + box.width() * 0.82, box.center().y()),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.58, box.y() + box.height() * 0.74),
        QPointF(box.x() + box.width() * 0.82, box.center().y()),
    )


def _search(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawEllipse(_r(box, 0.10, 0.10, 0.58, 0.58))
    p.drawLine(
        QPointF(box.x() + box.width() * 0.64, box.y() + box.height() * 0.64),
        QPointF(box.x() + box.width() * 0.90, box.y() + box.height() * 0.90),
    )


def _refresh(p: QPainter, box: QRectF, c: QColor) -> None:
    rect = _r(box, 0.14, 0.14, 0.72, 0.72)
    path = QPainterPath()
    path.arcMoveTo(rect, 60)
    path.arcTo(rect, 60, 260)
    p.drawPath(path)
    head = QPointF(
        rect.x() + rect.width() * (0.5 + 0.5 * math.cos(math.radians(60))),
        rect.y() + rect.height() * (0.5 + 0.5 * math.sin(math.radians(60))),
    )
    p.drawLine(head, QPointF(head.x() - box.width() * 0.02, head.y() + box.height() * 0.16))
    p.drawLine(head, QPointF(head.x() + box.width() * 0.16, head.y() + box.height() * 0.06))


def _copy(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawRoundedRect(_r(box, 0.14, 0.14, 0.52, 0.52), 4, 4)
    p.drawRoundedRect(_r(box, 0.34, 0.34, 0.52, 0.52), 4, 4)


def _eye(p: QPainter, box: QRectF, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(box.x() + box.width() * 0.08, box.center().y())
    path.quadTo(box.center().x(), box.top() + box.height() * 0.12,
                box.right() - box.width() * 0.08, box.center().y())
    path.quadTo(box.center().x(), box.bottom() - box.height() * 0.12,
                box.x() + box.width() * 0.08, box.center().y())
    p.drawPath(path)
    p.drawEllipse(_r(box, 0.36, 0.36, 0.28, 0.28))


def _hash(p: QPainter, box: QRectF, c: QColor) -> None:
    p.drawLine(
        QPointF(box.x() + box.width() * 0.38, box.y() + box.height() * 0.14),
        QPointF(box.x() + box.width() * 0.28, box.y() + box.height() * 0.86),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.68, box.y() + box.height() * 0.14),
        QPointF(box.x() + box.width() * 0.58, box.y() + box.height() * 0.86),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.18, box.y() + box.height() * 0.38),
        QPointF(box.x() + box.width() * 0.80, box.y() + box.height() * 0.38),
    )
    p.drawLine(
        QPointF(box.x() + box.width() * 0.14, box.y() + box.height() * 0.64),
        QPointF(box.x() + box.width() * 0.76, box.y() + box.height() * 0.64),
    )


def _layers(p: QPainter, box: QRectF, c: QColor) -> None:
    for i, y in enumerate((0.24, 0.44, 0.64)):
        path = QPainterPath()
        path.moveTo(box.center().x(), box.y() + box.height() * (y - 0.10))
        path.lineTo(box.right() - box.width() * 0.10, box.y() + box.height() * y)
        path.lineTo(box.center().x(), box.y() + box.height() * (y + 0.10))
        path.lineTo(box.left() + box.width() * 0.10, box.y() + box.height() * y)
        path.closeSubpath()
        if i == 0:
            p.drawPath(path)
        else:
            p.drawPath(path)


GLYPHS: Dict[str, _Drawer] = {
    "shield": _shield,
    "lock": _lock,
    "unlock": _unlock,
    "check": _check,
    "cross": _cross,
    "alert": _alert,
    "info": _info,
    "chart": _chart,
    "clock": _clock,
    "gear": _gear,
    "folder": _folder,
    "file": _file,
    "plus": _plus,
    "trash": _trash,
    "play": _play,
    "stop": _stop,
    "sun": _sun,
    "moon": _moon,
    "upload": _upload,
    "key": _key,
    "image": _image,
    "pulse": _pulse,
    "arrow-right": _arrow_right,
    "search": _search,
    "refresh": _refresh,
    "copy": _copy,
    "eye": _eye,
    "hash": _hash,
    "layers": _layers,
}


def pixmap(
    name: str,
    color: str = "#A0A9B8",
    size: int = 18,
    device_pixel_ratio: Optional[float] = None,
) -> QPixmap:
    """
    Render one glyph as a transparent pixmap.

    Unknown names return an empty pixmap rather than raising: a missing icon
    must never take the application down.
    """
    drawer = GLYPHS.get(name)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if drawer is None:
        return pm
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    _pen(painter, QColor(color), size)
    drawer(painter, QRectF(0, 0, size, size), QColor(color))
    painter.end()
    return pm


def icon(
    name: str,
    color: str = "#A0A9B8",
    size: int = 18,
) -> QIcon:
    """Render one glyph as a QIcon (for buttons, menus, …)."""
    # Drawn at twice the size with a device pixel ratio of 2, so the same
    # icon stays crisp on a HiDPI screen without a second asset.
    pm = pixmap(name, color, size * 2)
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


def has_glyph(name: str) -> bool:
    """True when `name` is a known glyph."""
    return name in GLYPHS
