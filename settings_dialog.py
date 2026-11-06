"""Окно «Настройки Капри»: характер, как часто пишет сама, «требует внимания», мат и интимный режим (18+),
тихие часы, тестовое уведомление. Настройки сохраняются в профиль пользователя и применяются сразу."""
from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QTimeEdit, QVBoxLayout, QWidget)

from persona import CHARACTERS

LEVELS = [("off", "ВЫКЛ"), ("rare", "РЕДКО"), ("normal", "ОБЫЧНО"), ("often", "ЧАСТО"), ("unlimited", "БЕЗ ОГРАНИЧЕНИЙ")]
HINT = ("Капри пишет сама не чаще выбранного: «Редко» — раз в час-два, «Обычно» — раз в 20–45 минут, «Часто» — раз в 8–20, "
        "«Без ограничений» — каждые 3–8 минут. В тихие часы молчит. Мат и интимный режим включаются отдельно "
        "и только для совершеннолетних.")

STYLE = """
QDialog { background:#16181c; color:#eef0f2; }
QScrollArea { background:#16181c; border:none; }
QWidget#body { background:#16181c; }
QLabel { color:#eef0f2; font-size:15px; }
QLabel#desc { color:#8d9299; font-size:12px; }
QLabel#hint { color:#a9adb3; font-size:12px; }
QLabel#title { font-size:16px; }
QFrame#line { background:#2a2d33; max-height:1px; min-height:1px; }
QComboBox, QTimeEdit { background:#1f2228; color:#e8d84a; border:1px solid #3a3a2a; padding:6px 10px;
                       font-weight:bold; min-width:150px; }
QComboBox QAbstractItemView { background:#1f2228; color:#e8d84a; selection-background-color:#3a3a2a; }
QPushButton#toggle { background:#2b2c20; color:#8d9299; border:1px solid #6d6a2a; min-width:78px; padding:8px; font-weight:bold; }
QPushButton#test { background:#1f2228; color:#eef0f2; border:1px solid #3a3a2a; padding:12px; text-align:left; font-size:15px; }
QPushButton#test:hover { border-color:#e8d84a; }
"""


class SettingsDialog(QDialog):
    def __init__(self, capri):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.capri = capri
        self.setWindowTitle("Капри — настройки")
        self.resize(520, 700)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        self.profile = QLabel()
        self.profile.setObjectName("desc")
        outer.addWidget(self.profile)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("body")
        area.viewport().setStyleSheet("background:#16181c;")
        self.rows = QVBoxLayout(body)
        area.setWidget(body)
        outer.addWidget(area, 1)

        self.character = QComboBox()
        for key, name in CHARACTERS.items():
            self.character.addItem(name.upper(), key)
        self._row("Характер", self.character)
        self.level = QComboBox()
        for key, name in LEVELS:
            self.level.addItem(name, key)
        self._row("Уведомления Капри", self.level)
        self.attention = self._toggle("Требует внимания",
                                      "Если давно не обращались, но сидите за ПК, Капри напишет серию из пяти "
                                      "реплик, всё настойчивее, пока не откликнетесь")
        self.swear = self._toggle("Мат (18+)", "Дерзкие фразы без цензуры в репликах и реакциях")
        self.intimate = self._toggle("Интимный режим (18+)",
                                     "Пошлые шутки при поглаживании мышью по Капри и при подключении зарядки "
                                     "(на ноутбуке). Свой звук: assets/sounds/charge.wav")
        self.perch = self._toggle("Сидеть на окнах",
                                  "Капри садится на верхний край активного окна и ездит вместе с ним. "
                                  "Перетащите её мышью на любое окно — останется на нём")
        self.quiet_from = self._time("Тихие часы · С")
        self.quiet_to = self._time("Тихие часы · До")
        test = QPushButton("🔔  Тестовое уведомление")
        test.setObjectName("test")
        test.clicked.connect(self.capri.test_notification)
        self.rows.addWidget(test)
        self.rows.addStretch(1)
        hint = QLabel(HINT)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.load()
        self.character.currentIndexChanged.connect(lambda: self.save(character=self.character.currentData()))
        self.level.currentIndexChanged.connect(lambda: self.capri.set_notify_level(self.level.currentData()))
        self.attention.toggled.connect(lambda on: self.save(needs_attention=on))
        self.perch.toggled.connect(self.capri.set_perch)
        self.swear.toggled.connect(lambda on: self.adult("swearing", self.swear, on))
        self.intimate.toggled.connect(lambda on: self.adult("intimate", self.intimate, on))
        self.quiet_from.timeChanged.connect(lambda t: self.save(quiet_from=t.toString("HH:mm")))
        self.quiet_to.timeChanged.connect(lambda t: self.save(quiet_to=t.toString("HH:mm")))

    # ----- строки -----
    def _line(self):
        sep = QFrame()
        sep.setObjectName("line")
        self.rows.addWidget(sep)

    def _row(self, title, widget, desc=None):
        box = QHBoxLayout()
        left = QVBoxLayout()
        label = QLabel(title)
        label.setObjectName("title")
        left.addWidget(label)
        if desc:
            d = QLabel(desc)
            d.setObjectName("desc")
            d.setWordWrap(True)
            left.addWidget(d)
        box.addLayout(left, 1)
        box.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.rows.addLayout(box)
        self._line()

    def _toggle(self, title, desc):
        button = QPushButton("OFF")
        button.setObjectName("toggle")
        button.setCheckable(True)
        button.toggled.connect(lambda on, b=button: self._paint(b))
        self._row(title, button, desc)
        return button

    ON_STYLE = "QPushButton { background-color:#e8d84a; color:#1b1c10; border:1px solid #e8d84a; min-width:78px; padding:8px; font-weight:bold; }"
    OFF_STYLE = "QPushButton { background-color:#2b2c20; color:#8d9299; border:1px solid #6d6a2a; min-width:78px; padding:8px; font-weight:bold; }"

    @classmethod
    def _paint(cls, button):
        """Текст и цвет переключателя: ON — жёлтый, OFF — тёмный."""
        on = button.isChecked()
        button.setText("ON" if on else "OFF")
        button.setStyleSheet(cls.ON_STYLE if on else cls.OFF_STYLE)

    def _time(self, title):
        edit = QTimeEdit()
        edit.setDisplayFormat("HH:mm")
        self._row(title, edit)
        return edit

    # ----- состояние -----
    def load(self):
        cfg = self.capri.cfg
        self.profile.setText("Профиль: " + self.capri.profiles.active()["name"] + "  •  настройки сохраняются в профиле")
        widgets = (self.character, self.level, self.attention, self.swear, self.intimate, self.perch,
                   self.quiet_from, self.quiet_to)
        for w in widgets:
            w.blockSignals(True)
        self.character.setCurrentIndex(max(0, self.character.findData(cfg.get("character", "bold"))))
        self.level.setCurrentIndex(max(0, self.level.findData(self.capri.effective_level())))
        self.attention.setChecked(bool(cfg.get("needs_attention", True)))
        adult = bool(cfg.get("adult_confirmed"))
        self.swear.setChecked(bool(cfg.get("swearing")) and adult)
        self.intimate.setChecked(bool(cfg.get("intimate")) and adult)
        self.perch.setChecked(bool(cfg.get("perch_windows", True)))
        self.quiet_from.setTime(QTime.fromString(cfg.get("quiet_from", "23:00"), "HH:mm"))
        self.quiet_to.setTime(QTime.fromString(cfg.get("quiet_to", "09:00"), "HH:mm"))
        for w in widgets:
            w.blockSignals(False)
        for b in (self.attention, self.swear, self.intimate, self.perch):
            self._paint(b)

    def save(self, **values):
        self.capri.update_settings(**values)

    def adult(self, key, button, on):
        """Мат и интимный режим: при первом включении спрашиваем про 18+."""
        if on and not self.capri.cfg.get("adult_confirmed"):
            ask = QMessageBox.question(self, "Только для взрослых",
                                       "Эти режимы только для совершеннолетних. Вам есть 18 лет?")
            if ask != QMessageBox.StandardButton.Yes:
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
                self._paint(button)
                return
            self.save(adult_confirmed=True)
        self.save(**{key: on})

    def showEvent(self, event):
        self.load()
        super().showEvent(event)
