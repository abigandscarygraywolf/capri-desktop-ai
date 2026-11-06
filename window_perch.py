"""Капри сидит на окнах: садится на верхний край активного окна и ездит вместе с ним.

Как работает:
- Включено (галочка «Сидеть на окнах» в трее или в настройках) — когда Капри на экране и ничем не занята,
  она молнией перескакивает на верх активного окна и дальше следует за ним при перетаскивании.
- Окно свернули, закрыли, развернули на весь экран или его заслонило другое — Капри спрыгивает
  (на другое активное окно или в свободное место экрана).
- Перетащили Капри мышью на верх любого окна — она «прилипает» именно к нему, даже если активным станет
  другое. Перетащили в пустое место — остаётся там, пока не спрячется.
- Полноэкранные игры и видео, рабочий стол, панель задач и собственные окна Капри не трогает.

Окна ищутся через WinAPI (ctypes, без лишних библиотек). Не на Windows модуль ничего не делает.
Поза на окнах — capri_roam.png (та же, что на прогулке). Нет её — Капри стоит на крае в обычной позе.
"""
import ctypes
import logging
import os
import sys
import time

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication

log = logging.getLogger("capri.perch")

SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                "Windows.UI.Core.CoreWindow", "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow",
                "MultitaskingViewFrame", "ForegroundStaging", "#32768", "tooltips_class32"}
MIN_W, MIN_H = 320, 160


# ---------------------------------------------------------------- координаты
def _screens():
    out = []
    for s in QGuiApplication.screens():
        g = s.geometry()
        out.append((g, s.devicePixelRatio() or 1.0))
    return out


def to_logical(x, y):
    """Физические пиксели WinAPI → координаты Qt. В Qt 6 у каждого экрана начало совпадает с физическим,
    а размер поделён на масштаб (125 %, 150 % …)."""
    for g, dpr in _screens():
        ox, oy = g.x(), g.y()
        if ox <= x < ox + g.width() * dpr and oy <= y < oy + g.height() * dpr:
            return ox + (x - ox) / dpr, oy + (y - oy) / dpr
    dpr = _screens()[0][1] if _screens() else 1.0
    return x / dpr, y / dpr


def to_physical(x, y):
    for g, dpr in _screens():
        if g.contains(QPoint(int(x), int(y))):
            return int(g.x() + (x - g.x()) * dpr), int(g.y() + (y - g.y()) * dpr)
    return int(x), int(y)


def screen_for(rect):
    s = QGuiApplication.screenAt(rect.center()) or QGuiApplication.screenAt(rect.topLeft())
    return s or QGuiApplication.primaryScreen()


# ---------------------------------------------------------------- WinAPI
class WinBackend:
    """Тонкая обёртка над user32/dwmapi. Все прямоугольники возвращает в координатах Qt."""

    def __init__(self):
        from ctypes import wintypes as wt
        self.wt = wt
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            self.dwm = ctypes.WinDLL("dwmapi")
        except OSError:
            self.dwm = None
        u = self.user32
        H = ctypes.c_void_p
        for name, args, res in (("GetForegroundWindow", [], H), ("IsWindowVisible", [H], wt.BOOL),
                                ("IsIconic", [H], wt.BOOL), ("IsZoomed", [H], wt.BOOL),
                                ("IsWindow", [H], wt.BOOL),
                                ("GetWindowRect", [H, ctypes.POINTER(wt.RECT)], wt.BOOL),
                                ("GetWindowThreadProcessId", [H, ctypes.POINTER(wt.DWORD)], wt.DWORD),
                                ("GetClassNameW", [H, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
                                ("GetWindowTextLengthW", [H], ctypes.c_int),
                                ("GetWindowLongW", [H, ctypes.c_int], ctypes.c_long),
                                ("WindowFromPoint", [wt.POINT], H), ("GetAncestor", [H, wt.UINT], H)):
            fn = getattr(u, name)
            fn.argtypes, fn.restype = args, res
        if self.dwm:
            self.dwm.DwmGetWindowAttribute.argtypes = [H, wt.DWORD, ctypes.c_void_p, wt.DWORD]
            self.dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        self.pid = os.getpid()

    def foreground(self):
        return self.user32.GetForegroundWindow() or None

    def _pid(self, hwnd):
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _cloaked(self, hwnd):
        if not self.dwm:
            return False
        val = self.wt.DWORD()
        ok = self.dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(val), ctypes.sizeof(val))  # DWMWA_CLOAKED
        return ok == 0 and val.value != 0

    def rect(self, hwnd):
        """Видимые границы окна (без невидимых рамок Windows 10/11) в координатах Qt или None."""
        r = self.wt.RECT()
        ok = False
        if self.dwm:  # DWMWA_EXTENDED_FRAME_BOUNDS
            ok = self.dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0
        if not ok and not self.user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        x1, y1 = to_logical(r.left, r.top)
        x2, y2 = to_logical(r.right, r.bottom)
        return QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))

    def usable(self, hwnd):
        """Окно, на котором можно сидеть: обычное видимое окно чужой программы, не свёрнуто,
        не развёрнуто на весь экран, не полноэкранное."""
        u = self.user32
        if not hwnd or not u.IsWindow(hwnd) or not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd) or u.IsZoomed(hwnd):
            return False
        if self._pid(hwnd) == self.pid or self._cloaked(hwnd):
            return False
        buf = ctypes.create_unicode_buffer(128)
        u.GetClassNameW(hwnd, buf, 128)
        if buf.value in SKIP_CLASSES or u.GetWindowTextLengthW(hwnd) == 0:
            return False
        ex = u.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        if ex & 0x80 or ex & 0x08000000:  # WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE
            return False
        r = self.rect(hwnd)
        if r is None or r.width() < MIN_W or r.height() < MIN_H:
            return False
        sg = screen_for(r).geometry()
        if r.contains(sg.adjusted(2, 2, -2, -2)):  # полноэкранная игра / видео
            return False
        return True

    def window_at(self, x, y):
        """Окно верхнего уровня в точке экрана (координаты Qt)."""
        px, py = to_physical(x, y)
        h = self.user32.WindowFromPoint(self.wt.POINT(px, py))
        return self.user32.GetAncestor(h, 2) if h else None  # GA_ROOT

    def covered(self, hwnd, x, y):
        """Точку окна hwnd заслоняет чужое окно (свои окна Капри не считаются)."""
        top = self.window_at(x, y)
        if not top or top == hwnd:
            return False
        return self._pid(top) != self.pid


def make_backend():
    if sys.platform != "win32":
        return None
    try:
        return WinBackend()
    except Exception:
        log.exception("Сидение на окнах недоступно")
        return None


# ---------------------------------------------------------------- логика
class Perch:
    """Решает, на каком окне сидеть, и двигает аватар. tick() вызывается из таймера аватара (~30 раз в с)."""

    SWITCH_DELAY = 1.2   # активное окно должно продержаться столько секунд, прежде чем Капри на него перепрыгнет
    COOLDOWN = 2.0       # после прыжка вниз — пауза
    COVER_CHECK = 0.4

    def __init__(self, avatar, backend="auto"):
        self.avatar = avatar
        self.backend = make_backend() if backend == "auto" else backend
        self.enabled = True
        self.hwnd = None
        self.rel = 0.62          # где на окне сидит: доля ширины от левого края
        self.pinned = False      # посадили мышью — не прыгает на другие окна
        self.free = False        # стащили мышью в пустое место — не садится, пока не спрячется
        self.sink = None         # на сколько ноги «свисают» ниже края; None — авто
        self._cand, self._cand_since = None, 0.0
        self._cooldown = 0.0
        self._next_cover, self._covered = 0.0, 0
        self._pads = {}

    @property
    def available(self):
        return self.backend is not None

    @property
    def active(self):
        return self.hwnd is not None

    def set_enabled(self, on):
        self.enabled = bool(on)
        if not on and self.hwnd:
            self.release(jump=True)

    # ----- геометрия -----
    def _pad(self, img):
        """Прозрачные строки сверху и снизу у картинки фигуры (чтобы ставить на край именно ноги)."""
        key = img.cacheKey()
        if key not in self._pads:
            w, h = img.width(), img.height()
            step = max(1, w // 80)

            def opaque(row):
                return any(img.pixelColor(x, row).alpha() > 40 for x in range(0, w, step))

            bottom = next((h - 1 - y for y in range(h - 1, -1, -1) if opaque(y)), 0)
            top = next((y for y in range(h) if opaque(y)), 0)
            dpr = img.devicePixelRatio() or 1.0
            self._pads[key] = (top / dpr, bottom / dpr)
        return self._pads[key]

    def spot(self, rect, rel=None):
        """Позиция окна аватара, при которой Капри сидит на верхнем крае rect. None — места нет."""
        from avatar import FIG_H, W  # здесь, чтобы не было циклического импорта
        img = self.avatar.perch_figure()
        top_pad, bottom_pad = self._pad(img)
        visible = FIG_H - top_pad - bottom_pad
        sink = self.sink if self.sink is not None else 3
        rel = self.rel if rel is None else rel
        x = rect.left() + rel * rect.width() - W / 2
        x = max(rect.left() - W * 0.25, min(rect.right() - W * 0.75, x))
        y = rect.top() - (FIG_H - bottom_pad) + sink
        avail = screen_for(rect).availableGeometry()
        if rect.top() - visible + sink < avail.top():  # окно у самого верха экрана — сидеть негде
            return None
        x = max(avail.left() - W * 0.25, min(avail.right() - W * 0.75, x))
        return QPoint(int(x), int(y))

    def _feet(self, rect):
        from avatar import W
        pos = self.avatar.pos()
        return pos.x() + W / 2, rect.top() + 10

    # ----- действия -----
    def perch_on(self, hwnd, teleport=True, rel=None, pinned=False):
        rect = self.backend.rect(hwnd)
        if rect is None:
            return False
        if rel is not None:
            self.rel = rel
        elif hwnd != self.hwnd:
            self.rel = 0.55 + 0.2 * ((hash(hwnd) >> 3) % 100) / 100  # у каждого окна своё место
        target = self.spot(rect)
        if target is None:
            return False
        self.hwnd, self.pinned, self.free = hwnd, pinned, False
        self._covered = 0
        if teleport and self.avatar.state == "visible":
            self.avatar.teleport(target)
        else:
            self.avatar.move(target)
        return True

    def release(self, jump=False, free=False):
        """Слезть с окна. jump — спрыгнуть молнией в свободное место."""
        was = self.hwnd
        self.hwnd, self.pinned = None, False
        self.free = free
        self._cooldown = time.time() + self.COOLDOWN
        if was and jump and self.avatar.state == "visible":
            self.avatar.teleport(self.avatar._random_spot())


    def reset(self):
        """Капри спряталась: всё забываем (стащили в пустое место — при следующем появлении снова сядет)."""
        self.hwnd, self.pinned, self.free, self._cand = None, False, False, None

    def place_now(self):
        """Перед появлением: сразу встать на активное окно (без молнии). True — встала."""
        if not (self.enabled and self.backend) or self.free:
            return False
        try:
            fg = self.backend.foreground()
            return bool(fg and self.backend.usable(fg) and self.perch_on(fg, teleport=False))
        except Exception:
            log.exception("perch place")
            return False

    def dropped(self):
        """Капри отпустили мышью: если ноги у верхнего края окна — садимся на него."""
        if not (self.enabled and self.backend):
            return
        from avatar import FIG_H, W
        img = self.avatar.perch_figure()
        _, bottom_pad = self._pad(img)
        pos = self.avatar.pos()
        fx, fy = pos.x() + W / 2, pos.y() + FIG_H - bottom_pad  # где сейчас ноги
        try:
            for dy in (6, 20, 40):
                hwnd = self.backend.window_at(fx, fy + dy)
                if hwnd and self.backend.usable(hwnd):
                    rect = self.backend.rect(hwnd)
                    if rect and abs(rect.top() - fy) <= 50:
                        rel = (fx - rect.left()) / max(1, rect.width())
                        if self.perch_on(hwnd, teleport=False, rel=max(0.05, min(0.95, rel)), pinned=True):
                            return
        except Exception:
            log.exception("perch drop")
        self.release(free=True)

    # ----- каждый кадр -----
    def tick(self, now=None):
        if not self.backend:
            return
        now = now or time.time()
        try:
            self._tick(now)
        except Exception:
            log.exception("perch tick")
            self.hwnd = None

    def _tick(self, now):
        b = self.backend
        if not self.enabled:
            return
        if self.hwnd:
            if not b.usable(self.hwnd):
                self.release(jump=True)
                return
            rect = b.rect(self.hwnd)
            target = self.spot(rect) if rect else None
            if target is None:
                self.release(jump=True)
                return
            if self.avatar.pos() != target:
                self.avatar.move(target)  # окно двигают — едем вместе с ним
            if now >= self._next_cover:
                self._next_cover = now + self.COVER_CHECK
                fx, fy = self._feet(rect)
                self._covered = self._covered + 1 if b.covered(self.hwnd, fx, fy) else 0
                if self._covered >= 2:  # окно заслонили — спрыгиваем
                    self.release(jump=True)
                    return
            if self.pinned:
                return
        if self.free or now < self._cooldown:
            return
        fg = b.foreground()
        if not fg or fg == self.hwnd:
            self._cand = None
            return
        if fg != self._cand:
            self._cand, self._cand_since = fg, now
            return
        if now - self._cand_since >= self.SWITCH_DELAY and b.usable(fg):
            self._cand = None
            self.perch_on(fg, teleport=True)
