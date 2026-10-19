"""
app.imaging
===========

Image metadata helpers and the two small preview widgets.

Kept apart from :mod:`app.widgets` because they know about *images* (PIL,
OptiCipher headers) rather than about *layout*. The window module re-exports
these names for backwards compatibility.
"""

from __future__ import annotations

import os

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QScrollArea, QVBoxLayout


def human_size(nbytes: int) -> str:
    """A compact, human-readable byte count."""
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 ** 2:
        return f"{nbytes / 1024:.1f} KiB"
    if nbytes < 1024 ** 3:
        return f"{nbytes / 1024 ** 2:.1f} MiB"
    return f"{nbytes / 1024 ** 3:.2f} GiB"


def describe_image(path: str) -> str:
    """
    Human-readable metadata for the info panel: name, format, colour mode,
    dimensions, file size, and whether the file carries an OptiCipher
    ciphertext header (an unauthenticated peek — the HMAC is only verified
    during decryption).
    """
    from opticipher import load_image
    from .workers import detect_opticipher_header

    lines = [os.path.basename(path)]
    try:
        size = human_size(os.path.getsize(path))
        with Image.open(path) as im:
            width, height = im.size
            extra = f"{im.format or '?'} · {im.mode} · {width}×{height} · {size}"
            frames = getattr(im, "n_frames", 1)
            if frames > 1:
                extra += f" · {frames} frames"
        lines.append(extra)
    except Exception as exc:  # noqa: BLE001 - info panel, never fatal
        lines.append(f"(cannot read image info: {exc})")
        return "\n".join(lines)
    try:
        header = detect_opticipher_header(load_image(path))
    except Exception:  # noqa: BLE001 - unreadable pixels just mean "no header"
        header = None
    if header:
        lines.append(
            "OptiCipher v{version} header · original {width}×{height} "
            "{channels} ch · PBKDF2 {iterations:,} iters · strip "
            "{strip_rows} rows".format(**header)
        )
    else:
        lines.append("No OptiCipher header — plain image")
    return "\n".join(lines)


class ClickableLabel(QLabel):
    """QLabel that emits `clicked` on a left-click (enlarge-on-click previews)."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ImageViewer(QDialog):
    """Enlarge dialog: the image at its native size inside a scroll area."""

    def __init__(self, path: str, info_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        self.setAttribute(Qt.WA_DeleteOnClose)
        pix = QPixmap(path)
        image_label = QLabel()
        image_label.setPixmap(pix)
        image_label.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(image_label)
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        if info_text:
            info = QLabel(info_text)
            info.setWordWrap(True)
            info.setTextInteractionFlags(Qt.TextSelectableByMouse)
            info.setObjectName("Muted")
            layout.addWidget(info)
        layout.addWidget(scroll, 1)
        # Size the dialog to the screen, not the image: large images scroll,
        # small ones simply center. Esc ( QDialog default) closes.
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(
            max(420, min(pix.width() + 48, screen.width() - 100)),
            max(320, min(pix.height() + 90, screen.height() - 120)),
        )
