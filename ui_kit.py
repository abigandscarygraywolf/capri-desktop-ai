"""Общие элементы интерфейса в стиле Капри: тёмные панели со срезанными углами, неоновые шкалы,
заголовок окна без рамки Windows (с перетаскиванием, «свернуть» и «закрыть»)."""
import os

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from paths import res

# палитра (по скриншотам)
BG = "#140f1b"          # фон окна профиля
BG_CHAT = "#0c0a10"     # фон чата
PANEL = "#1f1928"
PANEL_2 = "#241d2e"
TEXT = "#ece8f2"
MUTED = "#8b8396"
GREEN = "#3dff7c"
YELLOW = "#f8c43c"
PURPLE = "#7a3fe6"
RED = "#e0373f"
RED_DARK = "#3a1519"
BUBBLE = "#1b1922"
MONO = "Consolas, 'JetBrains Mono', 'Cascadia Mono', monospace"


def mono_font(size=9, bold=True):
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSizeF(size)
    f.setBold(bold)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 115)
    return f


def ui_pixmap(name):
    """Картинка из assets/ui (лицо Капри, стоящая поза). Нет файла — пустая картинка, окно всё равно откроется."""
    path = res("assets", "ui", name)
    return QPixmap(path) if os.path.isfile(path) else QPixmap()


def chamfer_path(rect, cut=10, corners=("tr",)):
    """Прямоугольник со срезанными углами: tl, tr, br, bl."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    c = {k: (cut if k in corners else 0) for k in ("tl", "tr", "br", "bl")}
    pts = [QPointF(x + c["tl"], y), QPointF(x + w - c["tr"], y), QPointF(x + w, y + c["tr"]),
           QPointF(x + w, y + h - c["br"]), QPointF(x + w - c["br"], y + h), QPointF(x + c["bl"], y + h),
           QPointF(x, y + h - c["bl"]), QPointF(x, y + c["tl"])]
    path = QPainterPath(pts[0])
    for p in pts[1:]:
        path.lineTo(p)
    path.closeSubpath()
    return path


class Panel(QWidget):
    """Панель со срезанными углами. border — цвет рамки или None."""

    def __init__(self, color=PANEL, cut=12, corners=("tr", "bl"), border=None, parent=None):
        super().__init__(parent)
        self.color, self.cut, self.corners, self.border = QColor(color), cut, corners, border
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = chamfer_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self.cut, self.corners)
        p.fillPath(path, self.color)
        if self.border:
            p.setPen(QPen(QColor(self.border), 1.4))
            p.drawPath(path)
        p.end()


class Bar(QWidget):
    """Неоновая шкала: value 0..1, цвет или градиент (два цвета)."""

    def __init__(self, colors=(GREEN,), height=12, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.value = 0.0
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, v):
        self.value = max(0.0, min(1.0, float(v)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = QRectF(self.rect())
        p.fillPath(chamfer_path(r, 4, ("br",)), QColor("#2c2438"))
        if self.value > 0:
            fill = QRectF(r.x(), r.y(), max(6.0, r.width() * self.value), r.height())
            if len(self.colors) > 1:
                g = QLinearGradient(fill.topLeft(), fill.topRight())
                g.setColorAt(0, QColor(self.colors[0]))
                g.setColorAt(1, QColor(self.colors[1]))
                brush = g
            else:
                brush = QColor(self.colors[0])
            p.fillPath(chamfer_path(fill, 4, ("br",)), brush)
        p.end()


class TitleBar(QWidget):
    """Заголовок окна: иконка, «CAPRI // РАЗДЕЛ», свои виджеты справа, «свернуть» и «закрыть».
    Окно таскается за заголовок."""

    def __init__(self, window, section, accent=GREEN, extra=None, bg="#100c15"):
        super().__init__(window)
        self.window_ = window
        self._drag = None
        self.setFixedHeight(46)
        self.setAutoFillBackground(False)
        self.bg = QColor(bg)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 10, 6)
        lay.setSpacing(10)
        icon = QLabel()
        pm = ui_pixmap("capri_face.png")
        if not pm.isNull():
            icon.setPixmap(pm.scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(icon)
        title = QLabel(f'<span style="color:{TEXT}">CAPRI</span>&nbsp;&nbsp;'
                       f'<span style="color:{accent}">// {section}</span>')
        title.setFont(mono_font(10))
        title.setStyleSheet("background:transparent;")
        icon.setStyleSheet("background:transparent;")
        lay.addWidget(title)
        lay.addStretch(1)
        for w in extra or []:
            lay.addWidget(w)
        for text, slot in (("—", window.showMinimized), ("✕", window.close)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(30, 28)
            b.setStyleSheet(f"QPushButton {{ background:transparent; color:{MUTED}; border:none; font-size:15px; }}"
                            f"QPushButton:hover {{ color:{TEXT}; }}")
            b.clicked.connect(slot)
            lay.addWidget(b)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.window_.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.window_.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _):
        self._drag = None


def chip_button(text, checkable=False, accent=GREEN):
    """Маленькая кнопка-«чип» в стиле заголовка (FULL на скрине)."""
    b = QPushButton(text)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFont(mono_font(8.5))
    b.setStyleSheet(
        f"QPushButton {{ background:#221b2b; color:{TEXT}; border:none; padding:5px 10px; }}"
        f"QPushButton:hover {{ background:#2c2338; }}"
        f"QPushButton:checked {{ background:{accent}; color:#0c0a10; }}")
    return b


def drop_point(w):
    return QPoint(w.width() // 2, w.height() // 2)
