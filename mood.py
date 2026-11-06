"""Самочувствие Капри: радость и усталость (0–100) и что она делает прямо сейчас.

Радость: от отношений с пользователем (memory) плюс недавние события — поглаживания, «спасибо», похвала,
разговор (+), грубость и игнор (−). События остывают за пару часов.
Усталость: от времени суток (ночью выше) и того, сколько Капри наговорила за последний час; отдых снижает.
Показывается в окне «Профиль Капри» и чуть влияет на тон нейросети.
"""
import datetime
import re
import threading
import time

EFFECTS = {"pet": 6, "thanks": 5, "praise": 8, "talk": 2, "insult": -14, "ignored": -10, "achievement": 6}
HALF_LIFE = 3600.0  # через час событие действует вполовину

JOY_LABELS = [(0, "грустит"), (20, "не в духе"), (40, "в порядке"), (60, "довольна"), (80, "в восторге")]
TIRED_LABELS = [(0, "полна сил"), (26, "бодрая"), (51, "устала"), (76, "засыпает")]


def _label(value, table):
    out = table[0][1]
    for floor, name in table:
        if value >= floor:
            out = name
    return out


def hour_tiredness(hour):
    if 0 <= hour < 6:
        return 60
    if hour < 9:
        return 35
    if hour < 18:
        return 15
    if hour < 23:
        return 30
    return 50


class Mood:
    def __init__(self, capri):
        self.capri = capri
        self.events = []      # (время, сила)
        self.spoken = []      # (время, секунды речи)
        self.lock = threading.Lock()

    # ----- события -----
    def record(self, kind):
        with self.lock:
            self.events.append((time.time(), EFFECTS.get(kind, 0)))
            self.events = [e for e in self.events if time.time() - e[0] < 4 * 3600][-200:]

    def on_text(self, text):
        low = (text or "").lower()
        if re.search(r"\b(дура|тупая|идиотк|дебил|заткнись|бесишь|ненавижу тебя|отвали)", low):
            self.record("insult")
        elif re.search(r"спасиб|благодар|\bспс\b", low):
            self.record("thanks")
        elif re.search(r"ты (молодец|умница|классная|крутая|лучшая|супер|хорошая|красивая|милая)|люблю тебя", low):
            self.record("praise")
        else:
            self.record("talk")

    def on_spoke(self, text):
        """Капри что-то сказала: примерно 1 секунда на 14 символов."""
        with self.lock:
            self.spoken.append((time.time(), len(text or "") / 14.0))
            self.spoken = [s for s in self.spoken if time.time() - s[0] < 3600][-300:]

    # ----- значения -----
    def joy(self):
        mem = getattr(self.capri, "memory", None)
        base = mem.score() if mem else 50
        now = time.time()
        with self.lock:
            bonus = sum(v * 0.5 ** ((now - t) / HALF_LIFE) for t, v in self.events)
        return int(max(0, min(100, base * 0.8 + 10 + bonus)))

    def tiredness(self):
        now = time.time()
        with self.lock:
            talk = sum(sec for t, sec in self.spoken if now - t < 3600)
        value = hour_tiredness(datetime.datetime.now().hour) + min(40, talk / 6)
        idle = now - getattr(self.capri, "last_user_interaction", now)
        if idle > 2 * 3600:  # долго не трогали — отдохнула
            value -= 15
        return int(max(0, min(100, value)))

    def state(self):
        """Что Капри делает сейчас: одно слово для строки «Сейчас …»."""
        c = self.capri
        if getattr(c, "speaking", False):
            return "говорит"
        roles = getattr(c, "roles", None)
        if roles and roles.role:
            return "играет роль"
        if getattr(c, "awake_until", 0) > time.time():
            return "слушает"
        mem = getattr(c, "memory", None)
        if mem and mem.level()[0] == "hurt":
            return "обижена"
        if c.in_quiet_hours() if hasattr(c, "in_quiet_hours") else False:
            return "дремлет"
        return "спокойна"

    def labels(self):
        j, t = self.joy(), self.tiredness()
        return {"joy": j, "joy_label": _label(j, JOY_LABELS), "tired": t, "tired_label": _label(t, TIRED_LABELS),
                "state": self.state()}

    def prompt(self):
        """Подсказка нейросети о самочувствии (пусто, если ничего особенного)."""
        j, t = self.joy(), self.tiredness()
        parts = []
        if t >= 76:
            parts.append("Ты очень устала и сонная: отвечай короче и мягче, можешь зевнуть словами.")
        elif t >= 51:
            parts.append("Ты немного устала: отвечай чуть спокойнее.")
        if j >= 85:
            parts.append("Ты сейчас в восторге и очень рада пользователю.")
        elif j < 25:
            parts.append("Ты сейчас не в духе.")
        return " ".join(parts)
