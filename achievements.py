"""Достижения и уровни Капри. Всё хранится в профиле (profiles.json): у каждого пользователя своё.

Опыт (XP) даётся за общение, «спасибо», новый день вместе и сами достижения. Уровень зависит от XP и
показывается в окне профиля. При получении достижения Капри говорит об этом, а в чате появляется строка 🏆.
"""
import datetime
import logging
import random
import threading
import time

from persona import STYLE, gendered

log = logging.getLogger("capri")

LEVELS = [(0, "Незнакомцы"), (20, "Знакомые"), (60, "Приятели"), (130, "Напарники"), (230, "Свои люди"),
          (370, "Команда"), (560, "Неразлучные"), (800, "Родные души"), (1100, "Легенда"), (1500, "Бессмертные")]
DAILY_MESSAGE_XP = 40   # за сообщения в день начисляется не больше этого, чтобы нельзя было «накрутить»
ACH_XP = 25

# id: (название, описание, иконка)
ACHIEVEMENTS = {
    "first": ("Первый разговор", "Написать или сказать Капри хоть что-нибудь", "👋"),
    "talk100": ("Болтун", "100 сообщений Капри", "💬"),
    "talk500": ("Не замолкает", "500 сообщений Капри", "📣"),
    "owl": ("Ночная сова", "10 сообщений с полуночи до 5 утра", "🦉"),
    "lark": ("Жаворонок", "5 сообщений с 5 до 8 утра", "🌅"),
    "polite": ("Вежливый", "10 раз сказать «спасибо»", "🙏"),
    "pets": ("Любитель погладить", "25 поглаживаний", "🤲"),
    "week": ("Неделя вместе", "7 разных дней с Капри", "📅"),
    "month": ("Месяц вместе", "30 разных дней с Капри", "🗓"),
    "streak": ("Без пропусков", "7 дней общения подряд", "🔥"),
    "memory": ("Хорошая память", "Капри запомнила о вас 10 фактов", "🧠"),
    "friends": ("Лучшие друзья", "Отношения 80 из 100", "💛"),
    "reconcile": ("Помирились", "Вернуть отношения после обиды", "🕊"),
    "gamer": ("Геймер", "Сыграть 2 часа подряд", "🎮"),
    "marathon": ("Марафонец", "Просидеть за компьютером 5 часов подряд", "🏃"),
    "birthday": ("С днём рождения!", "Получить поздравление Капри", "🎂"),
    "storyteller": ("Слушатель сказок", "30 сообщений в режиме «Сказка на ночь»", "📖"),
    "polyglot": ("Полиглот", "30 сообщений в режиме «Английский»", "🌍"),
    "adventurer": ("Искатель приключений", "30 сообщений в режиме «Квест»", "🗡"),
    "mentor": ("Достижение цели", "30 сообщений в режимах «Друг» и «Тренер»", "🎯"),
}
ANNOUNCE = {
    "bold": ["Эй, новое достижение: «{t}». Я бы тоже себя похвалила.", "«{t}» — готово. Не зазнавайся."],
    "soft": ["Поздравляю! Новое достижение: «{t}». Я тобой [горжусь|горжусь].",
             "У тебя новое достижение: «{t}». Это здорово."],
    "sarcastic": ["Достижение разблокировано: «{t}». Аплодисменты, занавес.", "«{t}». Кто бы мог подумать."],
    "calm": ["Новое достижение: «{t}».", "Получено достижение «{t}»."],
}
LEVEL_UP = ["Уровень {n}: «{t}». Мы растём.", "Новый уровень отношений: {n}, «{t}».",
            "Поздравляю, уровень {n}: «{t}»."]


def level_for(xp):
    n, title = 1, LEVELS[0][1]
    for i, (floor, name) in enumerate(LEVELS):
        if xp >= floor:
            n, title = i + 1, name
    return n, title


def level_progress(xp):
    """(уровень, название, XP внутри уровня, XP до следующего уровня или None на максимуме)."""
    n, title = level_for(xp)
    floor = LEVELS[n - 1][0]
    if n >= len(LEVELS):
        return n, title, xp - floor, None
    return n, title, xp - floor, LEVELS[n][0] - floor


class Achievements:
    def __init__(self, capri):
        self.capri = capri
        self.lock = threading.Lock()

    # ----- хранение -----
    @property
    def profile(self):
        return self.capri.profiles.active()

    def stats(self):
        s = self.profile.setdefault("stats", {})
        for key in ("messages", "thanks", "pets", "night", "morning", "days", "streak", "xp_today", "xp_day"):
            s.setdefault(key, 0)
        s.setdefault("last_day", "")
        s.setdefault("role_msgs", {})
        return s

    def earned(self):
        return self.profile.setdefault("achievements", {})

    def xp(self):
        return int(self.profile.get("xp", 0))

    # ----- события -----
    def on_message(self, text, role=None):
        """Пользователь написал или сказал Капри. Возвращает список реплик-объявлений."""
        low = (text or "").lower()
        hour = datetime.datetime.now().hour
        with self.lock:
            s = self.stats()
            s["messages"] += 1
            if 0 <= hour < 5:
                s["night"] += 1
            elif 5 <= hour < 8:
                s["morning"] += 1
            if any(w in low for w in ("спасиб", "благодар", "спс")):
                s["thanks"] += 1
                self._xp(2)
            if role:
                s["role_msgs"][role] = s["role_msgs"].get(role, 0) + 1
            self._xp(1, capped=True)
            self._new_day(s)
            return self._check()

    def on_pet(self):
        with self.lock:
            self.stats()["pets"] += 1
            return self._check()

    def on_event(self, kind, **kw):
        """kind: game (minutes), sitting (hours), birthday."""
        with self.lock:
            s = self.stats()
            if kind == "game" and kw.get("minutes", 0) >= 120:
                s["gamer"] = True
            elif kind == "sitting" and kw.get("hours", 0) >= 5:
                s["marathon"] = True
            elif kind == "birthday":
                s["birthday"] = True
            return self._check()

    # ----- внутренности -----
    def _xp(self, amount, capped=False):
        s = self.stats()
        today = datetime.date.today().isoformat()
        if s["xp_day"] != today:
            s["xp_day"], s["xp_today"] = today, 0
        if capped:
            amount = max(0, min(amount, DAILY_MESSAGE_XP - s["xp_today"]))
            s["xp_today"] += amount
        self.profile["xp"] = self.xp() + amount

    def _new_day(self, s):
        today = datetime.date.today()
        if s["last_day"] == today.isoformat():
            return
        yesterday = (today - datetime.timedelta(days=1)).isoformat()
        s["streak"] = s["streak"] + 1 if s["last_day"] == yesterday else 1
        s["last_day"] = today.isoformat()
        s["days"] += 1
        self._xp(5)

    def _conditions(self):
        s = self.stats()
        bond = self.capri.memory.score() if hasattr(self.capri, "memory") else 50
        rm = s["role_msgs"]
        if hasattr(self.capri, "memory") and self.capri.memory.level()[0] == "hurt":
            s["was_hurt"] = True
        facts = len(self.capri.memory.facts()) if hasattr(self.capri, "memory") else 0
        return {
            "first": s["messages"] >= 1, "talk100": s["messages"] >= 100, "talk500": s["messages"] >= 500,
            "owl": s["night"] >= 10, "lark": s["morning"] >= 5, "polite": s["thanks"] >= 10,
            "pets": s["pets"] >= 25, "week": s["days"] >= 7, "month": s["days"] >= 30,
            "streak": s["streak"] >= 7, "memory": facts >= 10, "friends": bond >= 80,
            "reconcile": bool(s.get("was_hurt")) and bond >= 45,
            "gamer": bool(s.get("gamer")), "marathon": bool(s.get("marathon")), "birthday": bool(s.get("birthday")),
            "storyteller": rm.get("story", 0) >= 30, "polyglot": rm.get("english", 0) >= 30,
            "adventurer": rm.get("quest", 0) >= 30, "mentor": rm.get("friend", 0) + rm.get("coach", 0) >= 30,
        }

    def _check(self):
        """Выдаёт новые достижения и повышение уровня. Возвращает реплики. Вызывать под self.lock."""
        before = level_for(self.xp())[0]
        done = self.earned()
        lines = []
        for key, ok in self._conditions().items():
            if ok and key not in done:
                done[key] = int(time.time())
                self.profile["xp"] = self.xp() + ACH_XP
                name = ACHIEVEMENTS[key][0]
                log.info("Достижение: %s", name)
                lines.append(gendered(random.choice(ANNOUNCE.get(STYLE["character"], ANNOUNCE["bold"]))).format(t=name))
        after, title = level_for(self.xp())
        if after > before:
            lines.append(random.choice(LEVEL_UP).format(n=after, t=title))
        if lines:
            self.capri.profiles.save()
        elif self.stats()["messages"] % 10 == 0:
            self.capri.profiles.save()  # счётчики не теряются при закрытии
        return lines
