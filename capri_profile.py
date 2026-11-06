"""Окно «Профиль Капри»: уровень и опыт, радость и усталость, что она делает сейчас, статистика
и последние достижения. Обновляется само, пока открыто."""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizeGrip, QVBoxLayout, QWidget)

from achievements import ACHIEVEMENTS, level_progress
from ui_kit import (BG, GREEN, MUTED, PANEL, PURPLE, TEXT, YELLOW, Bar, Panel, TitleBar, mono_font, ui_pixmap)

from achievements import LEVELS


def _label(text, size=10, color=TEXT, bold=False, mono=False):
    lab = QLabel(text)
    if mono:
        lab.setFont(mono_font(size, bold))
    else:
        f = lab.font()
        f.setPointSizeF(size)
        f.setBold(bold)
        lab.setFont(f)
    lab.setStyleSheet(f"color:{color}; background:transparent;")
    return lab


class LevelBox(Panel):
    """Зелёный квадрат с номером уровня."""

    def __init__(self):
        super().__init__(GREEN, cut=14, corners=("tr", "bl"))
        self.setFixedSize(104, 104)
        self.n = 1

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        f = QFont()
        f.setPointSize(30)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#0c0a10"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.n))
        p.end()


class Tile(Panel):
    def __init__(self, caption):
        super().__init__(PANEL, cut=10, corners=("tr", "bl"))
        self.setMinimumHeight(84)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.value = _label("0", 18, TEXT, True)
        lay.addWidget(self.value)
        lay.addWidget(_label(caption, 8.5, MUTED, mono=True, bold=False))


class Chip(Panel):
    def __init__(self):
        super().__init__(PANEL, cut=8, corners=("tr", "bl"))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.text = _label("", 9.5, TEXT, mono=True, bold=False)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.text)


class CapriProfile(QWidget):
    def __init__(self, capri, open_user_profile=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Window)
        self.capri = capri
        self.open_user_profile = open_user_profile
        self.setWindowTitle("Капри — профиль")
        self.resize(940, 640)
        self.setObjectName("capriProfile")
        self.setStyleSheet(f"QWidget#capriProfile {{ background:{BG}; }} QLabel {{ background:transparent; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, "ПРОФИЛЬ"))

        body = QHBoxLayout()
        body.setContentsMargins(20, 18, 20, 14)
        body.setSpacing(22)
        outer.addLayout(body, 1)

        # ----- слева: Капри во весь рост и что она делает -----
        left = QVBoxLayout()
        left.setSpacing(14)
        portrait = Panel("#1b1524", cut=16, corners=("tr", "bl"))
        pl = QVBoxLayout(portrait)
        pl.setContentsMargins(10, 14, 10, 14)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background:transparent;")
        self._stand = ui_pixmap("capri_stand.png")
        pl.addWidget(self.image, 1)
        portrait.setFixedWidth(270)
        left.addWidget(portrait, 1)
        status = Panel(PANEL, cut=10, corners=("tr", "bl"))
        status.setFixedWidth(270)
        sl = QVBoxLayout(status)
        sl.setContentsMargins(14, 12, 14, 12)
        self.status = _label("", 11, TEXT)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(self.status)
        left.addWidget(status)
        body.addLayout(left)

        # ----- справа -----
        right = QVBoxLayout()
        right.setSpacing(16)
        body.addLayout(right, 1)

        lvl = QHBoxLayout()
        lvl.setSpacing(20)
        self.level_box = LevelBox()
        lvl.addWidget(self.level_box)
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(_label("УРОВЕНЬ", 9, MUTED, True, mono=True))
        self.xp_bar = Bar((GREEN, YELLOW), 14)
        col.addWidget(self.xp_bar)
        self.xp_text = _label("", 9.5, TEXT, mono=True)
        col.addWidget(self.xp_text)
        lvl.addLayout(col, 1)
        right.addLayout(lvl)

        chips = QHBoxLayout()
        chips.setSpacing(12)
        self.chip_level, self.chip_bond = Chip(), Chip()
        chips.addWidget(self.chip_level)
        chips.addWidget(self.chip_bond)
        chips.addStretch(1)
        right.addLayout(chips)

        moods = QHBoxLayout()
        moods.setSpacing(22)
        self.joy_text, self.joy_bar = self._mood(moods, "Радость", YELLOW)
        self.tired_text, self.tired_bar = self._mood(moods, "Усталость", PURPLE)
        right.addLayout(moods)

        right.addWidget(_label("СТАТИСТИКА", 9, MUTED, True, mono=True))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles = {}
        for i, (key, caption) in enumerate((("messages", "сообщений"), ("days", "дней вместе"),
                                            ("pets", "поглаживаний"), ("ach", "достижений"))):
            t = Tile(caption)
            self.tiles[key] = t
            grid.addWidget(t, 0, i)
        right.addLayout(grid)

        head = QHBoxLayout()
        head.addWidget(_label("ДОСТИЖЕНИЯ", 9, MUTED, True, mono=True))
        head.addWidget(_label("— последние полученные", 9, MUTED, mono=True))
        head.addStretch(1)
        right.addLayout(head)
        self.ach_row = QHBoxLayout()
        self.ach_row.setSpacing(12)
        right.addLayout(self.ach_row)
        right.addStretch(1)

        # фиолетовая полоса снизу, как на скрине, и уголок для изменения размера
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        line = QWidget()
        line.setFixedHeight(6)
        line.setStyleSheet(f"background:{PURPLE};")
        foot.addWidget(line, 1)
        grip = QSizeGrip(self)
        grip.setStyleSheet("background:transparent;")
        foot.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(foot)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def _mood(self, parent, title, color):
        box = QVBoxLayout()
        box.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(_label(title, 10.5, TEXT))
        row.addStretch(1)
        text = _label("", 9.5, TEXT, mono=True)
        row.addWidget(text)
        box.addLayout(row)
        bar = Bar((color,), 12)
        box.addWidget(bar)
        parent.addLayout(box, 1)
        return text, bar

    # ----- данные -----
    def refresh(self):
        c = self.capri
        achv, mem = c.achv, c.memory
        xp = achv.xp()
        n, title, have, need = level_progress(xp)
        self.level_box.n = n
        self.level_box.update()
        if need:
            self.xp_bar.set_value(have / need)
            self.xp_text.setText(f"{have} / {need} опыта до {n + 1} уровня")
            nxt = LEVELS[n][1]
            self.chip_level.text.setText(f'Уровень {n + 1}: <span style="color:{YELLOW}">«{nxt}»</span>')
        else:
            self.xp_bar.set_value(1)
            self.xp_text.setText(f"{xp} опыта · максимальный уровень")
            self.chip_level.text.setText(f'<span style="color:{YELLOW}">«{title}»</span> — выше некуда')
        key, bond_name = mem.level()
        self.chip_bond.text.setText(f'💛&nbsp; Отношения: <span style="color:{YELLOW}">{bond_name}</span>'
                                    f' · {mem.score()}')

        m = c.mood.labels()
        self.joy_text.setText(f"{m['joy']} · {m['joy_label']}")
        self.joy_bar.set_value(m["joy"] / 100)
        self.tired_text.setText(f"{m['tired']} · {m['tired_label']}")
        self.tired_bar.set_value(m["tired"] / 100)
        self.status.setText(f'Сейчас <span style="color:{GREEN}">{m["state"]}</span>, '
                            f'{m["joy_label"]}, {m["tired_label"]}')

        s = achv.stats()
        done = achv.earned()
        self.tiles["messages"].value.setText(str(s["messages"]))
        self.tiles["days"].value.setText(str(s["days"]))
        self.tiles["pets"].value.setText(str(s["pets"]))
        self.tiles["ach"].value.setText(f"{len(done)}/{len(ACHIEVEMENTS)}")

        recent = sorted(done.items(), key=lambda kv: -kv[1])[:3]
        sig = tuple(k for k, _ in recent)
        if getattr(self, "_ach_sig", None) != sig:
            self._ach_sig = sig
            while self.ach_row.count():
                item = self.ach_row.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            for k, ts in recent:
                name, _desc, icon = ACHIEVEMENTS[k]
                chip = Chip()
                chip.text.setText(f"{icon}&nbsp; {name}")
                chip.setToolTip(time.strftime("получено %d.%m.%Y", time.localtime(ts)))
                self.ach_row.addWidget(chip)
            if not recent:
                self.ach_row.addWidget(_label("Пока ни одного. Поболтайте с Капри!", 9.5, MUTED, mono=True))
            more = QPushButton("Все достижения →")
            more.setCursor(Qt.CursorShape.PointingHandCursor)
            more.setFont(mono_font(9.5, False))
            more.setStyleSheet(f"QPushButton {{ background:transparent; color:{TEXT}; border:1px dashed #4a4055;"
                               f" padding:10px 14px; }} QPushButton:hover {{ border-color:{GREEN}; }}")
            if self.open_user_profile:
                more.clicked.connect(self.open_user_profile)
            self.ach_row.addWidget(more)
            self.ach_row.addStretch(1)
        self._fit_image()

    def _fit_image(self):
        if self._stand.isNull():
            return
        size = self.image.size()
        if size.width() < 10 or size.height() < 10:
            return
        self.image.setPixmap(self._stand.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_image()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self.timer.start(2000)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)
