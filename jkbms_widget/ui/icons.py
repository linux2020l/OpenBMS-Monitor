"""Small vector icons drawn with QPainter (no image files, no icon fonts).

Each icon is drawn in a 24x24 coordinate box and scaled to the requested size.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _poly(*pts: tuple[float, float]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in pts])


@lru_cache(maxsize=256)  # icons are requested on every UI refresh; draw each once
def pixmap(name: str, color: str, size: int = 24) -> QPixmap:
    ratio = 2.0  # draw at 2x for sharp icons on high-DPI screens
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    c = QColor(color)
    pen = QPen(c, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    if name == "bolt":
        p.setBrush(c)
        p.drawPolygon(_poly((13.5, 2), (4.5, 13.5), (11, 13.5), (9.5, 22), (19.5, 9.5), (13, 9.5)))
    elif name == "pulse":
        p.drawPolyline(_poly((2, 12), (6.5, 12), (9.5, 5), (14, 19), (17, 12), (22, 12)))
    elif name == "volt":
        p.drawEllipse(QRectF(2.5, 2.5, 19, 19))
        p.drawPolyline(_poly((8, 8), (12, 16.5), (16, 8)))
    elif name == "thermo":
        path = QPainterPath()
        path.addRoundedRect(QRectF(9.5, 2.5, 5, 13), 2.5, 2.5)
        p.drawPath(path)
        p.setBrush(c)
        p.drawEllipse(QPointF(12, 18), 3.6, 3.6)
        p.drawLine(QPointF(12, 8), QPointF(12, 16))
    elif name == "clock":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.drawPolyline(_poly((12, 7), (12, 12), (15.5, 14)))
    elif name == "check":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, 22, 22))
        p.setPen(QPen(QColor("#10131a"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(_poly((7, 12.5), (10.5, 16), (17, 8.5)))
    elif name == "warning":
        p.setBrush(c)
        p.drawPolygon(_poly((12, 2.5), (22, 20.5), (2, 20.5)))
        p.setPen(QPen(QColor("#10131a"), 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(12, 9), QPointF(12, 14))
        p.drawPoint(QPointF(12, 17.5))
    elif name == "info":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, 22, 22))
        p.setPen(QPen(QColor("#10131a"), 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(12, 11), QPointF(12, 17))
        p.drawPoint(QPointF(12, 7))
    elif name == "bluetooth":
        p.drawPolyline(_poly((6.5, 7.5), (17, 16.5), (12, 21), (12, 3), (17, 7.5), (6.5, 16.5)))
    elif name == "battery":
        path = QPainterPath()
        path.addRoundedRect(QRectF(2, 7, 18, 10), 2.5, 2.5)
        p.drawPath(path)
        p.setBrush(c)
        p.drawRect(QRectF(20.5, 10, 1.5, 4))
        p.setPen(QPen(c, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(_poly((12, 8.5), (9, 12.5), (13, 12), (10, 15.5)))
    elif name == "expand":
        p.drawPolyline(_poly((14, 4), (20, 4), (20, 10)))
        p.drawPolyline(_poly((10, 20), (4, 20), (4, 14)))
        p.drawLine(QPointF(20, 4), QPointF(13.5, 10.5))
        p.drawLine(QPointF(4, 20), QPointF(10.5, 13.5))
    elif name == "checkmark":  # plain tick for checkbox / menu indicators
        p.setPen(QPen(c, 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(_poly((5, 12.5), (10, 17.5), (19, 7)))
    elif name == "gear":
        # 8 teeth around a ring, drawn as one polygon, with a hole in the middle.
        pts = []
        for k in range(16):
            a = math.pi * 2 * k / 16
            for da, r in ((-0.16, 10.5 if k % 2 == 0 else 8.0), (0.16, 10.5 if k % 2 == 0 else 8.0)):
                pts.append((12 + r * math.cos(a + da), 12 + r * math.sin(a + da)))
        path = QPainterPath()
        path.addPolygon(_poly(*pts))
        path.closeSubpath()
        path.addEllipse(QPointF(12, 12), 3.4, 3.4)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPath(path)  # odd-even fill leaves the centre hole empty
    elif name == "menu":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        for y in (5, 12, 19):
            p.drawEllipse(QPointF(12, y), 2, 2)
    elif name == "collapse":
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "close":
        p.drawLine(QPointF(6, 6), QPointF(18, 18))
        p.drawLine(QPointF(18, 6), QPointF(6, 18))
    elif name == "chart":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        for x, h in ((3, 7), (9.5, 12), (16, 18)):
            p.drawRoundedRect(QRectF(x, 21 - h, 4.5, h), 1.5, 1.5)
    p.end()
    return pm


def paint_battery(
    p: QPainter,
    rect: QRectF,
    soc: float | None,
    fill: str,
    outline: str,
    charging: bool = False,
    fault: bool = False,
) -> None:
    """Horizontal phone-style battery icon inside `rect`.

    soc None = no data (empty outline). Bolt while charging. Faults: red
    round badge with '!' on the top-right corner (owner's choice).
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    nub_w = rect.width() * 0.08
    body = QRectF(rect.left() + 1, rect.top() + 1, rect.width() - nub_w - 3, rect.height() - 2)
    radius = body.height() * 0.22
    p.setPen(QPen(QColor(outline), 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(body, radius, radius)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(outline))
    nub_h = body.height() * 0.4
    p.drawRoundedRect(QRectF(body.right() + 1, body.center().y() - nub_h / 2, nub_w, nub_h), 1, 1)

    if soc is not None:
        inner = body.adjusted(2.6, 2.6, -2.6, -2.6)
        w = max(1.5, inner.width() * max(0.0, min(soc, 100.0)) / 100)
        p.setBrush(QColor(fill))
        p.drawRoundedRect(QRectF(inner.left(), inner.top(), w, inner.height()), 1.5, 1.5)

    if charging:
        # Lightning bolt centered, white with a dark edge so it reads on any fill.
        cx, cy, s = body.center().x(), body.center().y(), body.height() / 24
        bolt = _poly(*[(cx + (x - 12) * s * 1.05, cy + (y - 12) * s * 1.05) for x, y in
                       ((13.5, 2), (5, 13.5), (11, 13.5), (9.5, 22), (19, 9.5), (12.5, 9.5))])
        p.setPen(QPen(QColor("#10131a"), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(bolt)

    if fault:
        r = body.height() * 0.42
        c = QPointF(body.right() - r * 0.2, body.top() + r * 0.2)
        p.setPen(QPen(QColor("#10131a"), 1.2))
        p.setBrush(QColor("#ef4444"))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor("#ffffff"), max(1.4, r * 0.32), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x(), c.y() - r * 0.45), QPointF(c.x(), c.y() + r * 0.12))
        p.drawPoint(QPointF(c.x(), c.y() + r * 0.5))
    p.restore()


@lru_cache(maxsize=256)
def icon(name: str, color: str, size: int = 24) -> QIcon:
    return QIcon(pixmap(name, color, size))


@lru_cache(maxsize=64)
def battery_level_icon(soc: float | None, color: str, alarm: bool = False) -> QIcon:
    """Tray / app icon: vertical battery filled to the SOC level."""
    out = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 32, size / 32)
        c = QColor(color)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(12, 1.5, 8, 3.5), 1, 1)  # terminal
        p.setPen(QPen(c, 2.6))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(6.5, 5, 19, 25.5), 3.5, 3.5)  # body
        if soc is not None:
            level = max(0.0, min(soc, 100.0)) / 100
            h = 19.5 * level
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(9.5, 27.5 - h, 13, h), 1.5, 1.5)
        if alarm:
            p.setBrush(QColor("#ef4444"))
            p.setPen(QPen(QColor("#10131a"), 1.5))
            p.drawEllipse(QRectF(19, 19, 12, 12))
        p.end()
        out.addPixmap(pm)
    return out
