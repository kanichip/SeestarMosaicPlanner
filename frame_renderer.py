from pathlib import Path

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

def create_frame_png(path, number, width, height):
    w = 800
    h = max(100, round(w * height / width))

    image = QImage(w, h, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(QPen(QColor(255, 235, 30), 6))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(5, 5, w - 11, h - 11)

    painter.setPen(QColor(255, 255, 80))
    font = QFont("Arial")
    font.setPixelSize(48)
    font.setBold(True)
    painter.setFont(font)

    painter.drawText(
        QRect(24, 16, 200, 75),
        Qt.AlignLeft | Qt.AlignTop,
        str(number)
    )
    painter.end()

    if not image.save(str(path), "PNG"):
        raise OSError(f"PNG保存失敗: {path}")
