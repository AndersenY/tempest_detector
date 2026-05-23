from __future__ import annotations

import os
import sys

from PyQt6.QtGui import QIcon, QPixmap


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
    ico_path = resource_path("image", "icon.ico")
    if os.path.exists(ico_path):
        icon.addFile(ico_path)

    png_path = resource_path("image", "icon.png")
    if os.path.exists(png_path):
        pixmap = QPixmap(png_path)
        if not pixmap.isNull():
            for size in (16, 24, 32, 48, 64, 128, 256):
                icon.addPixmap(pixmap.scaled(size, size))
        else:
            icon.addFile(png_path)
    return icon
