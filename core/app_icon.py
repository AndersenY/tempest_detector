from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

from gui.icons import ANTENNA, make_pixmap


def resource_path(*parts: str) -> str:
    """Return a resource path for source runs and frozen Windows builds."""
    bases = [
        getattr(sys, "_MEIPASS", None),
        os.path.join(os.path.dirname(sys.executable), "_internal"),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ]
    for base in bases:
        if not base:
            continue
        path = os.path.join(base, *parts)
        if os.path.exists(path):
            return path
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *parts)


def app_icon() -> QIcon:
    icon = QIcon()

    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_app_bar_icon_pixmap(size))
    if not icon.isNull():
        return icon

    ico_path = resource_path("image", "icon.ico")
    if os.path.exists(ico_path):
        icon.addFile(ico_path)
        return icon

    png_path = resource_path("image", "icon.png")
    if os.path.exists(png_path):
        pixmap = QPixmap(png_path)
        if not pixmap.isNull():
            for size in (16, 24, 32, 48, 64, 128, 256):
                scaled = pixmap.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                icon.addPixmap(scaled)
        else:
            icon.addFile(png_path)
    return icon


def _app_bar_icon_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#4fb3a0"))
    radius = max(3.0, size * 5 / 22)
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    glyph_size = max(12, round(size * 16 / 22))
    glyph = make_pixmap(ANTENNA, "#ffffff", glyph_size)
    if not glyph.isNull():
        x = (size - glyph.width()) // 2
        y = (size - glyph.height()) // 2
        painter.drawPixmap(x, y, glyph)
    painter.end()

    return pixmap
