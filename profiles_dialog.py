"""Профили пользователей: выбор и создание профиля, отношения с Капри, что она о вас помнит, день рождения."""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from achievements import ACHIEVEMENTS, level_progress
from memory import birthday_words, parse_birthday

STYLE = """
QDialog { background:#16181c; color:#eef0f2; }
QLabel { color:#eef0f2; font-size:14px; }
QLabel#head { color:#e8d84a; font-size:12px; font-weight:bold; letter-spacing:1px; margin-top:10px; }
QLabel#desc { color:#8d9299; font-size:12px; }
QComboBox, QLineEdit, QListWidget { background:#1f2228; color:#eef0f2; border:1px solid #3a3a2a; padding:6px; }
QListWidget::item { padding:4px; }
QListWidget::item:selected { background:#3a3a2a; color:#e8d84a; }
QPushButton { background:#1f2228; color:#eef0f2; border:1px solid #3a3a2a; padding:7px 12px; }
QPushButton:hover { border-color:#e8d84a; }
QProgressBar { background:#1f2228; border:1px solid #3a3a2a; height:14px; text-align:center; color:#eef0f2; }
QProgressBar::chunk { background:#e8d84a; }
"""
BOND_HINT = {
    "hurt": "Капри обижена. Поговорите с ней, поблагодарите — она оттает.",
    "cool": "Отношения прохладные. Чаще общайтесь, и станет теплее.",
    "neutral": "Обычные отношения. Общение, «спасибо» и похвала их улучшают.",
    "friends": "Вы дружите. Игнор и грубость охлаждают отношения.",
    "close": "Вы очень близки. Не пропадайте надолго: за дни без общения она остывает.",
}


class ProfilesDialog(QDialog):
    def __init__(self, capri):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.capri = capri
        self.setWindowTitle("Капри — профиль")
        self.resize(480, 760)
        self.setStyleSheet(STYLE)
        lay = QVBoxLayout(self)

        lay.addWidget(self._head("АКТИВНЫЙ ПОЛЬЗОВАТЕЛЬ"))
        self.combo = QComboBox()
        lay.addWidget(self.combo)
        row = QHBoxLayout()
        select = QPushButton("Переключить")
        add = QPushButton("Новый профиль")
        select.clicked.connect(self.select)
        add.clicked.connect(self.add)
        row.addWidget(select)
        row.addWidget(add)
        lay.addLayout(row)

        lay.addWidget(self._head("ОТНОШЕНИЯ С КАПРИ"))
        self.bond_label = QLabel()
        lay.addWidget(self.bond_label)
        self.bond_bar = QProgressBar()
        self.bond_bar.setRange(0, 100)
        lay.addWidget(self.bond_bar)
        self.bond_hint = QLabel()
        self.bond_hint.setObjectName("desc")
        self.bond_hint.setWordWrap(True)
        lay.addWidget(self.bond_hint)

        lay.addWidget(self._head("УРОВЕНЬ И ДОСТИЖЕНИЯ"))
        self.level_label = QLabel()
        lay.addWidget(self.level_label)
        self.xp_bar = QProgressBar()
        self.xp_bar.setRange(0, 100)
        self.xp_bar.setFormat("")
        lay.addWidget(self.xp_bar)
        self.ach = QListWidget()
        self.ach.setMaximumHeight(150)
        lay.addWidget(self.ach)

        lay.addWidget(self._head("ДЕНЬ РОЖДЕНИЯ"))
        row = QHBoxLayout()
        self.birthday = QLineEdit()
        self.birthday.setPlaceholderText("например, 5 марта или 05.03")
        save_bd = QPushButton("Сохранить")
        save_bd.clicked.connect(self.save_birthday)
        row.addWidget(self.birthday, 1)
        row.addWidget(save_bd)
        lay.addLayout(row)

        lay.addWidget(self._head("ЧТО КАПРИ О ВАС ПОМНИТ"))
        hint = QLabel("Голосом или в чате: «запомни, что я люблю рок», «забудь, что…», «что ты обо мне знаешь».")
        hint.setObjectName("desc")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.facts = QListWidget()
        lay.addWidget(self.facts, 1)
        row = QHBoxLayout()
        add_fact = QPushButton("Добавить…")
        del_fact = QPushButton("Удалить выбранное")
        add_fact.clicked.connect(self.add_fact)
        del_fact.clicked.connect(self.delete_fact)
        row.addWidget(add_fact)
        row.addWidget(del_fact)
        lay.addLayout(row)
        self.refresh()

    @staticmethod
    def _head(text):
        label = QLabel(text)
        label.setObjectName("head")
        return label

    def refresh(self):
        profiles = self.capri.profiles
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in profiles.data["profiles"]:
            self.combo.addItem(p["name"], p["id"])
            if p["id"] == profiles.active()["id"]:
                self.combo.setCurrentIndex(self.combo.count() - 1)
        self.combo.blockSignals(False)
        mem = self.capri.memory
        score = mem.score()
        key, name = mem.level()
        self.bond_label.setText(f"{name} · {score}/100")
        self.bond_bar.setValue(score)
        self.bond_bar.setFormat("")
        self.bond_hint.setText(BOND_HINT[key])
        n, title, have, need = level_progress(self.capri.achv.xp())
        self.level_label.setText(f"Уровень {n}: {title}  ·  {self.capri.achv.xp()} XP" +
                                 ("" if need else "  ·  максимум"))
        self.xp_bar.setValue(100 if not need else int(100 * have / need))
        done = self.capri.achv.earned()
        self.ach.clear()
        for key, (name, desc, icon) in sorted(ACHIEVEMENTS.items(), key=lambda kv: kv[0] not in done):
            got = key in done
            item = QListWidgetItem(f"{icon} {name}" + (f"  ·  {time.strftime('%d.%m.%Y', time.localtime(done[key]))}"
                                                       if got else f"  ·  {desc}"))
            if not got:
                item.setForeground(Qt.GlobalColor.gray)
            self.ach.addItem(item)
        bd = profiles.active().get("birthday")
        self.birthday.setText(birthday_words(bd) if bd else "")
        self.facts.clear()
        for f in mem.facts():
            item = QListWidgetItem("«" + f["text"] + "»  ·  " + time.strftime("%d.%m.%Y", time.localtime(f.get("ts", 0))))
            item.setData(Qt.ItemDataRole.UserRole, f["text"])
            self.facts.addItem(item)
        if not mem.facts():
            self.facts.addItem("Пока пусто")

    def select(self):
        self.capri.switch_profile(self.combo.currentData())
        self.refresh()

    def add(self):
        name, ok = QInputDialog.getText(self, "Новый профиль", "Как Капри должна обращаться к пользователю?")
        if not ok or not name.strip():
            return
        gender, ok = QInputDialog.getItem(self, "Обращение", "Род обращения:", ["Мужской", "Женский"], 0, False)
        if not ok:
            return
        self.capri.profiles.add(name, "female" if gender == "Женский" else "male")
        self.capri.switch_profile(self.capri.profiles.active()["id"])
        self.refresh()
        QMessageBox.information(self, "Капри", "Профиль создан и активирован.")

    def save_birthday(self):
        text = self.birthday.text().strip()
        mem = self.capri.memory
        if not text:
            self.capri.profiles.active().pop("birthday", None)
            mem.save()
            self.refresh()
            return
        parts = text.replace(".", " ").replace("/", " ").split()
        value = parse_birthday(parts[0], parts[1]) if len(parts) >= 2 else None
        if not value:
            QMessageBox.warning(self, "Капри", "Не поняла дату. Напишите, например: 5 марта или 05.03.")
            return
        self.capri.profiles.active()["birthday"] = value
        mem.save()
        self.refresh()

    def add_fact(self):
        text, ok = QInputDialog.getText(self, "Капри запомнит", "Что запомнить (своими словами, например «я люблю рок»):")
        if ok and text.strip():
            self.capri.memory.remember(text)
            self.refresh()

    def delete_fact(self):
        item = self.facts.currentItem()
        text = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not text:
            return
        mem = self.capri.memory
        with mem.lock:
            facts = mem.facts()
            facts[:] = [f for f in facts if f["text"] != text]
            mem.save()
        self.refresh()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
