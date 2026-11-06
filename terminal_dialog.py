"""Окно чата и команд в стиле Капри: пузыри со срезанными углами, иконка Капри, имя вашего профиля
над вашими сообщениями, красная рамка. История сохраняется (у каждого профиля своя), ответ нейросети
приходит потоком, пока Капри думает — в пузыре «думает…».

Снизу: «глаз» — показать или спрятать Капри на экране; поле ввода (Enter — отправить);
трубка — позвать Капри голосом, а пока она думает или говорит, кнопка становится «стоп».
В заголовке: режим (общение или команда Windows), ролевой режим и «очистить»."""
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QVBoxLayout, QWidget)

from ui_kit import (BG_CHAT, BUBBLE, MUTED, RED, RED_DARK, TEXT, YELLOW, TitleBar, chamfer_path, chip_button,
                    mono_font, ui_pixmap)

ROLE_NAMES = [("", "ОБЫЧНЫЙ РАЗГОВОР"), ("story", "📖 СКАЗКА НА НОЧЬ"), ("english", "🌍 АНГЛИЙСКИЙ"),
              ("friend", "🤝 СОВЕТ КАК ДРУГ"), ("coach", "🎯 ТРЕНЕР"), ("quest", "🗡 КВЕСТ")]
DOTS = ["", ".", "..", "..."]
BAR = 4          # красная полоска у пузыря
CUT = 12         # срезанный угол пузыря
BUBBLE_MAX = 0.72


class Bubble(QWidget):
    """Пузырь сообщения: шапка («КАПРИ 04:14» или имя профиля) и текст. Свой — справа, тёмно-красный."""

    def __init__(self, mine, header, text, muted=False):
        super().__init__()
        self.mine = mine
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins((14 if mine else BAR + 16), 9, (BAR + 16 if mine else 18), 11)
        lay.setSpacing(3)
        self.head = QLabel(header)
        self.head.setFont(mono_font(7.5))
        self.head.setStyleSheet(f"color:{'#c9a7aa' if mine else MUTED}; background:transparent;")
        if mine:
            self.head.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.head)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f = self.body.font()
        f.setPointSizeF(11.5)
        f.setWeight(f.Weight.DemiBold)
        self.body.setFont(f)
        if mine:
            self.body.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.body)
        self.set_text(text, muted)

    def set_text(self, text, muted=False):
        self.body.setText(text)
        self._fit()
        self.body.setStyleSheet(f"color:{MUTED if muted else TEXT}; background:transparent;"
                                + ("font-style:italic;" if muted else ""))

    def set_max(self, width):
        self.body.setMaximumWidth(max(120, width - (BAR + 34)))
        self._fit()

    def _fit(self):
        """Ширина по тексту: короткое сообщение — узкий пузырь, длинное — до максимума, потом перенос."""
        fm = self.body.fontMetrics()
        natural = max((fm.horizontalAdvance(line) for line in (self.body.text() or " ").split("\n")), default=0)
        self.body.setMinimumWidth(min(natural + 8, self.body.maximumWidth()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        if self.mine:
            box = QRectF(r.x(), r.y(), r.width() - BAR - 2, r.height())
            p.fillPath(chamfer_path(box, CUT, ("tl",)), QColor(RED_DARK))
            p.fillRect(QRectF(r.right() - BAR, r.y() + CUT, BAR, r.height() - CUT), QColor(RED))
        else:
            p.fillRect(QRectF(r.x(), r.y() + 4, BAR, r.height() - 4), QColor(RED))
            box = QRectF(r.x() + BAR + 2, r.y(), r.width() - BAR - 2, r.height())
            p.fillPath(chamfer_path(box, CUT, ("tr",)), QColor(BUBBLE))
        p.end()


class Avatar(QLabel):
    """Иконка Капри слева от её сообщений."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(42, 42)
        pm = ui_pixmap("capri_face.png")
        if not pm.isNull():
            self.setPixmap(pm.scaled(42, 42, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        self.setStyleSheet("background:transparent;")


class IconButton(QPushButton):
    """Кнопка с нарисованной иконкой: eye, phone или stop. round — круглая (трубка)."""

    def __init__(self, kind, round_=False):
        super().__init__()
        self.kind, self.round = kind, round_
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(48, 48)
        self.setStyleSheet("background:transparent; border:none;")
        self.on = True

    def set_kind(self, kind):
        if kind != self.kind:
            self.kind = kind
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        hover = self.underMouse()
        if self.round:
            p.setBrush(QColor("#5a2a31" if self.kind == "stop" else ("#454456" if hover else "#38374a")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(r)
        else:
            p.setBrush(QColor("#15121a"))
            p.setPen(QPen(QColor("#77737f" if hover else "#4d4955"), 1.5))
            p.drawRect(r.adjusted(4, 4, -4, -4))
        c = QPointF(r.center())
        color = QColor("#d9d6de" if self.on else "#6c6873")
        if self.kind == "eye":
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(c.x() - 11, c.y()))
            path.quadTo(QPointF(c.x(), c.y() - 10), QPointF(c.x() + 11, c.y()))
            path.quadTo(QPointF(c.x(), c.y() + 10), QPointF(c.x() - 11, c.y()))
            p.drawPath(path)
            p.setBrush(color)
            p.drawEllipse(c, 3.2, 3.2)
            if not self.on:
                p.drawLine(QPointF(c.x() - 11, c.y() + 9), QPointF(c.x() + 11, c.y() - 9))
        elif self.kind == "phone":
            p.setPen(QPen(QColor("#e9e6ee"), 5.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            arc = QRectF(c.x() - 11, c.y() - 11, 22, 22)
            p.drawArc(arc, 150 * 16, 120 * 16)  # трубка: дуга с толстыми закруглёнными концами
            p.setPen(QPen(QColor("#e9e6ee"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPoint(QPointF(c.x() - 7.5, c.y() - 7.5))
            p.drawPoint(QPointF(c.x() + 7.5, c.y() + 7.5))
        elif self.kind == "stop":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffd9dc"))
            p.drawRect(QRectF(c.x() - 7, c.y() - 7, 14, 14))
        p.end()


class ChatList(QWidget):
    """Лента сообщений."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG_CHAT};")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 16, 22, 16)
        self.lay.setSpacing(14)
        self.lay.addStretch(1)
        self.bubbles = []
        self.width_hint = 520

    def clear(self):
        while self.lay.count() > 1:
            item = self.lay.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                _drop_layout(item.layout())
        self.bubbles = []

    def add_row(self, widget_or_layout):
        if isinstance(widget_or_layout, QWidget):
            self.lay.addWidget(widget_or_layout)
        else:
            self.lay.addLayout(widget_or_layout)

    def fit(self, width):
        self.width_hint = width
        for b in self.bubbles:
            b.set_max(int(width * BUBBLE_MAX))


def _drop_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _drop_layout(item.layout())


class TerminalDialog(QWidget):
    def __init__(self, capri):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Window)
        self.capri = capri
        self.setWindowTitle("Капри — чат")
        self.resize(580, 800)
        self.setStyleSheet(f"""
            QWidget {{ color:{TEXT}; }}
            QScrollArea {{ background:{BG_CHAT}; border:none; }}
            QScrollBar:vertical {{ background:transparent; width:6px; margin:4px 0; }}
            QScrollBar::handle:vertical {{ background:{RED}; min-height:40px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
            QComboBox {{ background:#221b2b; color:{TEXT}; border:none; padding:5px 10px; }}
            QComboBox QAbstractItemView {{ background:#1b1922; color:{TEXT}; selection-background-color:{RED_DARK}; }}
            QLineEdit {{ background:#0a080d; color:{TEXT}; border:2px solid {RED}; padding:10px 14px;
                         font-size:15px; }}
            QLineEdit:focus {{ border-color:#ff5a61; }}
        """)

        # ----- заголовок: режим, роль, очистить -----
        self.chat_btn = chip_button("ОБЩЕНИЕ", True, RED)
        self.cmd_btn = chip_button("КОМАНДА", True, RED)
        self.chat_btn.setToolTip("Разговор с Капри (нейросеть)")
        self.cmd_btn.setToolTip("Команды Windows: «открой ютуб», «громкость 30»")
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.chat_btn)
        group.addButton(self.cmd_btn)
        self.chat_btn.setChecked(True)
        group.buttonToggled.connect(lambda *_: self._mode_changed())
        self.role = QComboBox()
        self.role.setFont(mono_font(8.5))
        for key, name in ROLE_NAMES:
            self.role.addItem(name, key)
        self.role.setToolTip("Ролевой режим. Выйти можно словом «хватит».")
        self.role.currentIndexChanged.connect(lambda: self.capri.set_role(self.role.currentData()))
        clear = chip_button("ОЧИСТИТЬ")
        clear.setToolTip("Удалить переписку этого профиля")
        clear.clicked.connect(self.clear)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 4, 4)  # место под красную рамку справа и снизу
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self, "ЧАТ", accent=RED, extra=[self.chat_btn, self.cmd_btn, self.role, clear],
                                 bg="#0f0c13"))

        self.list = ChatList()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.list)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll, 1)

        # ----- ввод -----
        bottom = QWidget()
        bottom.setStyleSheet(f"background:{BG_CHAT};")
        row = QHBoxLayout(bottom)
        row.setContentsMargins(14, 10, 14, 14)
        row.setSpacing(10)
        self.eye = IconButton("eye")
        self.eye.setToolTip("Показать или спрятать Капри на экране")
        self.eye.clicked.connect(self.toggle_capri)
        row.addWidget(self.eye)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Напиши Капри...")
        self.entry.returnPressed.connect(self.send)
        row.addWidget(self.entry, 1)
        self.call = IconButton("phone", round_=True)
        self.call.setToolTip("Позвать Капри голосом")
        self.call.clicked.connect(self.call_or_stop)
        row.addWidget(self.call)
        outer.addWidget(bottom)

        self.messages = []      # [(role, text, ts)] — то, что показано в окне
        self.pending = None     # набегающий ответ Капри (None — не ждём)
        self.pending_bubble = None
        self.profile_id = None
        self.dots = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.state_timer = QTimer(self)
        self.state_timer.timeout.connect(self._sync_call_button)
        self.state_timer.start(300)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)
        capri.text_reply.connect(self.receive)
        capri.chat_started.connect(self.on_started)
        capri.chat_delta.connect(self.on_delta)
        capri.chat_finished.connect(self.on_finished)
        capri.chat_note.connect(self.on_note)
        capri.chat_award.connect(self.on_award)
        capri.role_changed.connect(self.on_role)
        self.load_history()

    # ----- рамка -----
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_CHAT))
        w, h = self.width(), self.height()
        p.fillRect(w - 4, 30, 4, h - 30, QColor(RED))   # красная полоса справа
        p.fillRect(40, h - 4, w - 40, 4, QColor(RED))   # и снизу
        p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.grip.move(self.width() - self.grip.width() - 4, self.height() - self.grip.height() - 4)
        self.list.fit(self.scroll.viewport().width() - 60)

    # ----- история -----
    @property
    def user_name(self):
        return (self.capri.profiles.active().get("name") or "ТЫ").upper()

    def load_history(self):
        pid = self.capri.profiles.active()["id"]
        self.profile_id = pid
        self.messages = [(r["role"], r["text"], r.get("ts", 0)) for r in self.capri.history.load(pid, 200)]
        self.render()

    def render(self):
        """Полная перерисовка ленты (при открытии, смене профиля, очистке)."""
        self.list.clear()
        self._day = None
        self.pending_bubble = None
        for role, text, ts in self.messages:
            self._append(role, text, ts)
        if not self.messages:
            hint = QLabel("Здесь пока пусто. Скажи Капри «привет».")
            hint.setFont(mono_font(9, False))
            hint.setStyleSheet(f"color:{MUTED};")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.add_row(hint)
        if self.pending is not None:
            self._show_pending()
        self._scroll_down()

    def _append(self, role, text, ts):
        d = time.strftime("%d.%m.%Y", time.localtime(ts)) if ts else None
        if d and d != getattr(self, "_day", None):
            self._day = d
            sep = QLabel(f"— {d} —")
            sep.setFont(mono_font(8, False))
            sep.setStyleSheet("color:#5d5966;")
            sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.add_row(sep)
        clock = time.strftime("%H:%M", time.localtime(ts)) if ts else ""
        if role in ("note", "ach"):
            lab = QLabel(("🏆  " if role == "ach" else "⚠  ") + text)
            lab.setWordWrap(True)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setFont(mono_font(8.5, role == "ach"))
            lab.setStyleSheet(f"color:{YELLOW if role == 'ach' else MUTED};")
            self.list.add_row(lab)
            return None
        mine = role == "user"
        bubble = Bubble(mine, f"{self.user_name if mine else 'КАПРИ'}   {clock}".strip(), text)
        bubble.set_max(int(self.list.width_hint * BUBBLE_MAX))
        self.list.bubbles.append(bubble)
        row = QHBoxLayout()
        row.setSpacing(10)
        if mine:
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(Avatar(), 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(bubble)
            row.addStretch(1)
        self.list.add_row(row)
        return bubble

    def _add(self, role, text):
        self.messages.append((role, text, int(time.time())))
        self.messages = self.messages[-300:]
        if len(self.messages) == 1:
            self.render()  # убрать «Здесь пока пусто»
            return
        self._append(role, text, self.messages[-1][2])
        self._scroll_down()

    def _show_pending(self):
        self.pending_bubble = self._append("capri", "", int(time.time()))
        self._update_pending()

    def _update_pending(self):
        if not self.pending_bubble:
            return
        if self.pending:
            self.pending_bubble.set_text(self.pending)
        else:
            self.pending_bubble.set_text("думает" + DOTS[self.dots], muted=True)

    def _scroll_down(self):
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    # ----- ввод -----
    def _mode_changed(self):
        chat = self.chat_btn.isChecked()
        self.entry.setPlaceholderText("Напиши Капри..." if chat else "Команда для Windows: «открой ютуб»…")

    def send(self):
        value = self.entry.text().strip()
        if not value:
            return
        self.entry.clear()
        chat = self.chat_btn.isChecked()
        self._add("user", value)
        if not chat:
            self.capri.history.add(self.profile_id, "user", value)
        self.capri.text_command(value, chat=chat)

    def busy(self):
        return self.pending is not None or getattr(self.capri, "speaking", False)

    def call_or_stop(self):
        if self.busy():
            self.capri.stop_chat()
        else:
            self.capri.call_from_click()  # Капри слушает голос

    def _sync_call_button(self):
        busy = self.busy()
        self.call.set_kind("stop" if busy else "phone")
        self.call.setToolTip("Остановить" if busy else "Позвать Капри голосом")

    def toggle_capri(self):
        self.eye.on = not self.eye.on
        self.eye.update()
        (self.capri.summon if self.eye.on else self.capri.vanish).emit()

    def stop(self):
        self.capri.stop_chat()

    def clear(self):
        ask = QMessageBox.question(self, "Очистить чат", "Удалить всю переписку этого профиля? Капри забудет и "
                                   "контекст разговора (факты о вас в памяти останутся).")
        if ask == QMessageBox.StandardButton.Yes:
            self.capri.clear_chat()
            self.messages = []
            self.render()

    # ----- ответы -----
    def on_started(self):
        self.pending = ""
        self.dots = 0
        self.timer.start(400)
        if self.pending_bubble is None:
            self._show_pending()
        else:
            self._update_pending()
        self._scroll_down()

    def _tick(self):
        if self.pending == "":
            self.dots = (self.dots + 1) % len(DOTS)
            self._update_pending()

    def on_delta(self, piece):
        if self.pending is None:
            self.on_started()
        self.pending += piece
        self._update_pending()
        self._scroll_down()

    def on_finished(self, answer):
        self.timer.stop()
        self.pending = None
        bubble, self.pending_bubble = self.pending_bubble, None
        self.messages.append(("capri", answer, int(time.time())))
        self.messages = self.messages[-300:]
        if bubble:
            bubble.set_text(answer)  # тот же пузырь, где набегал текст
        else:
            self._append("capri", answer, self.messages[-1][2])
        self._scroll_down()

    def on_note(self, text):
        self.capri.history.add(self.profile_id, "note", text)
        self._add("note", text)

    def on_award(self, text):
        self._add("ach", text)

    def on_role(self, key):
        """Режим включили голосом или словами в чате — переключаем список, не запуская повторно."""
        self.role.blockSignals(True)
        self.role.setCurrentIndex(max(0, self.role.findData(key or "")))
        self.role.blockSignals(False)

    def receive(self, answer):
        """Ответы на команды Windows и служебные сообщения (смена профиля и т. п.)."""
        if self.capri.profiles.active()["id"] != self.profile_id:
            self.load_history()
        # сохраняем всегда: окно могли закрыть, пока команда выполнялась, — при открытии ответ будет на месте
        self.capri.history.add(self.profile_id, "capri", answer)
        self._add("capri", answer)

    def showEvent(self, event):
        if self.capri.profiles.active()["id"] != self.profile_id:
            self.load_history()
        super().showEvent(event)
        self.list.fit(self.scroll.viewport().width() - 60)
        self.entry.setFocus()
        self._scroll_down()

    def sizeHint(self):
        return QSize(580, 800)
