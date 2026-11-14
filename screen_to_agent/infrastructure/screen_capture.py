from __future__ import annotations

from PySide6.QtGui import QCursor, QGuiApplication, QPixmap, QScreen


def screen_under_cursor() -> QScreen:
    screen = QGuiApplication.screenAt(QCursor.pos())
    if screen is not None:
        return screen
    primary = QGuiApplication.primaryScreen()
    if primary is None:
        raise RuntimeError("没有可用的显示器。")
    return primary


def capture_screen(screen: QScreen) -> QPixmap:
    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        raise RuntimeError("屏幕抓取失败。")
    return pixmap
