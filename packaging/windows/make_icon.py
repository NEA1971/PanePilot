"""Erzeugt aus dem SVG-Programmsymbol eine PNG-Datei (PyInstaller macht daraus das .ico)."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication(sys.argv)
renderer = QSvgRenderer(sys.argv[1])
img = QImage(256, 256, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
renderer.render(p)
p.end()
img.save(sys.argv[2])
