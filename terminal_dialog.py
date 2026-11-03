"""Окно чата и команд. История сохраняется (у каждого профиля своя), ответ нейросети приходит потоком,
пока Капри думает — видно «Капри думает…», есть кнопки «Остановить» и «Очистить»."""
import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTextBrowser, QVBoxLayout)

STYLE = """
QDialog { background:#16181c; color:#eef0f2; }
QLabel { color:#8d9299; font-size:12px; }
QTextBrowser { background:#1b1d22; color:#eef0f2; border:1px solid #2a2d33; padding:8px; font-size:14px; }
QLineEdit { background:#1f2228; color:#eef0f2; border:1px solid #3a3a2a; padding:9px; font-size:14px; }
QLineEdit:focus { border-color:#e8d84a; }
QComboBox { background:#1f2228; color:#e8d84a; border:1px solid #3a3a2a; padding:6px; font-weight:bold; }
QComboBox QAbstractItemView { background:#1f2228; color:#e8d84a; selection-background-color:#3a3a2a; }
QPushButton { background:#1f2228; color:#eef0f2; border:1px solid #3a3a2a; padding:8px 12px; }
QPushButton:hover { border-color:#e8d84a; }
QPushButton#send { background:#e8d84a; color:#1b1c10; border:1px solid #e8d84a; font-weight:bold; }
QPushButton:disabled { color:#5d6066; border-color:#2a2d33; }
"""
USER_COLOR, CAPRI_COLOR, NOTE_COLOR, TIME_COLOR = "#e8d84a", "#ff9ec4", "#8d9299", "#5d6066"
ROLE_NAMES = [("", "Обычный разговор"), ("story", "📖 Сказка на ночь"), ("english", "🌍 Практика английского"),
              ("friend", "🤝 Совет как друг"), ("coach", "🎯 Тренер и планировщик"), ("quest", "🗡 Текстовый квест")]
DOTS = ["", ".", "..", "..."]


def _esc(text):
    return html.escape(text).replace("\n", "<br>")


class TerminalDialog(QDialog):
    def __init__(self, capri):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.capri = capri
        self.setWindowTitle("Капри — чат и команды")
        self.resize(600, 520)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.title = QLabel()
        top.addWidget(self.title, 1)
        clear = QPushButton("Очистить")
        clear.clicked.connect(self.clear)
        top.addWidget(clear)
        layout.addLayout(top)
        self.mode = QComboBox()
        self.mode.addItem("💬 Общение с Капри", "chat")
        self.mode.addItem("⚙ Команда Windows", "command")
        layout.addWidget(self.mode)
        self.role = QComboBox()
        for key, name in ROLE_NAMES:
            self.role.addItem(name, key)
        self.role.setToolTip("Ролевой режим: Капри играет роль. Выйти можно словом «хватит».")
        self.role.currentIndexChanged.connect(lambda: self.capri.set_role(self.role.currentData()))
        layout.addWidget(self.role)
        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(True)
        layout.addWidget(self.log, 1)
        self.status = QLabel("")
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Напиши Капри или дай команду…")
        self.entry.returnPressed.connect(self.send)
        row.addWidget(self.entry, 1)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)
        self.send_btn = QPushButton("Отправить")
        self.send_btn.setObjectName("send")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        self.messages = []      # [(role, text, ts)] — то, что показано в окне
        self.pending = None     # набегающий ответ Капри (None — не ждём)
        self.profile_id = None
        self.dots = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        capri.text_reply.connect(self.receive)
        capri.chat_started.connect(self.on_started)
        capri.chat_delta.connect(self.on_delta)
        capri.chat_finished.connect(self.on_finished)
        capri.chat_note.connect(self.on_note)
        capri.chat_award.connect(self.on_award)
        capri.role_changed.connect(self.on_role)
        self.load_history()

    # ----- история -----
    def load_history(self):
        pid = self.capri.profiles.active()["id"]
        self.profile_id = pid
        self.messages = [(r["role"], r["text"], r.get("ts", 0)) for r in self.capri.history.load(pid, 200)]
        self.title.setText("Профиль: " + self.capri.profiles.active()["name"] + "  •  история сохраняется")
        self.render()

    def render(self):
        parts = []
        day = None
        for role, text, ts in self.messages:
            d = time.strftime("%d.%m.%Y", time.localtime(ts)) if ts else None
            if d and d != day:
                day = d
                parts.append(f'<p align="center" style="color:{TIME_COLOR}">— {d} —</p>')
            parts.append(self._bubble(role, text, ts))
        if self.pending is not None:
            body = _esc(self.pending) if self.pending else f'<i style="color:{NOTE_COLOR}">думает{DOTS[self.dots]}</i>'
            parts.append(self._bubble("capri", None, None, raw=body))
        self.log.setHtml("".join(parts) or f'<p style="color:{NOTE_COLOR}">Здесь пока пусто. Скажи Капри «привет».</p>')
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.ensureCursorVisible()

    @staticmethod
    def _bubble(role, text, ts, raw=None):
        clock = time.strftime("%H:%M", time.localtime(ts)) if ts else ""
        stamp = f' <span style="color:{TIME_COLOR};font-size:11px">{clock}</span>' if clock else ""
        body = raw if raw is not None else _esc(text)
        if role == "user":
            return f'<p><b style="color:{USER_COLOR}">Вы</b>{stamp}<br>{body}</p>'
        if role == "ach":
            return f'<p style="color:{USER_COLOR}"><b>🏆 {body}</b></p>'
        if role == "note":
            return f'<p style="color:{NOTE_COLOR}"><i>⚠ {body}</i></p>'
        return f'<p><b style="color:{CAPRI_COLOR}">Капри</b>{stamp}<br>{body}</p>'

    def _add(self, role, text):
        self.messages.append((role, text, int(time.time())))
        self.messages = self.messages[-300:]
        self.render()

    # ----- ввод -----
    def send(self):
        value = self.entry.text().strip()
        if not value:
            return
        self.entry.clear()
        chat = self.mode.currentData() == "chat"
        self._add("user", value)
        if not chat:
            self.capri.history.add(self.profile_id, "user", value)
        self.capri.text_command(value, chat=chat)

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
        self.stop_btn.setEnabled(True)
        self.status.setText("Капри думает…")
        self.timer.start(400)
        self.render()

    def _tick(self):
        if self.pending == "":
            self.dots = (self.dots + 1) % len(DOTS)
            self.render()

    def on_delta(self, piece):
        if self.pending is None:
            self.pending = ""
        self.pending += piece
        self.status.setText("Капри печатает…")
        self.render()

    def on_finished(self, answer):
        self.pending = None
        self.timer.stop()
        self.stop_btn.setEnabled(False)
        self.status.setText("")
        self._add("capri", answer)

    def on_note(self, text):
        self.messages.append(("note", text, int(time.time())))
        self.capri.history.add(self.profile_id, "note", text)
        self.render()

    def on_award(self, text):
        self.messages.append(("ach", text, int(time.time())))
        self.render()

    def on_role(self, key):
        """Режим включили голосом или словами в чате — переключаем список, не запуская повторно."""
        self.role.blockSignals(True)
        self.role.setCurrentIndex(max(0, self.role.findData(key or "")))
        self.role.blockSignals(False)

    def receive(self, answer):
        """Ответы на команды Windows и служебные сообщения (смена профиля и т. п.)."""
        if self.capri.profiles.active()["id"] != self.profile_id:
            self.load_history()
        if not self.isVisible():
            return
        self.capri.history.add(self.profile_id, "capri", answer)
        self._add("capri", answer)

    def showEvent(self, event):
        if self.capri.profiles.active()["id"] != self.profile_id:
            self.load_history()
        super().showEvent(event)
        self.entry.setFocus()
