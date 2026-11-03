"""Капри сама требует внимания и реагирует на зарядку.

AttentionWatcher («Требует внимания»): если вы давно не обращались к Капри, но сидите за компьютером,
она пишет серию из пяти реплик, каждая настойчивее предыдущей, и замолкает до вашей реакции.
PowerWatcher: реплика (и необязательный звук) при подключении и отключении зарядки на ноутбуке.
Оба уважают тихие часы, полноэкранный режим и не перебивают разговор (Capri.may_initiate).
"""
import ctypes
import logging
import os
import random
import threading
import time

from persona import styled

log = logging.getLogger("capri")

# пауза до следующей реплики серии (минуты) после реплики №1…№4
GAPS = (10, 7, 5, 3)
AWAY_SECONDS = 300  # нет ввода дольше — пользователя за компьютером нет, не зовём


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def input_idle_seconds():
    """Сколько секунд пользователь не трогал мышь и клавиатуру."""
    try:
        info = _LastInput()
        info.cbSize = ctypes.sizeof(_LastInput)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
    except Exception:
        return 0.0


def generate(capri, prompt, fallback):
    """Реплика от локальной нейросети (если она запущена), иначе готовая фраза."""
    try:
        if capri.local and capri.local.running():
            from activity import _clean
            text = _clean(capri.local.comment(prompt))
            if text:
                return text
    except Exception:
        log.exception("Реплика через нейросеть не получилась")
    return fallback


class AttentionWatcher:
    def __init__(self, capri):
        self.capri = capri
        self.level = 0          # сколько реплик серии уже сказано
        self.next_at = 0.0
        self.seen = capri.last_user_interaction

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="attention").start()

    def enabled(self):
        c = self.capri
        return bool(c.cfg.get("needs_attention", True)) and c.effective_level() != "off"

    def _loop(self):
        while True:
            time.sleep(20)
            try:
                self._tick()
            except Exception:
                log.exception("Сбой «требует внимания»")
                time.sleep(30)

    def _tick(self):
        c = self.capri
        now = time.time()
        if c.last_user_interaction > self.seen:  # вы обратились к Капри: серия сброшена
            self.seen = c.last_user_interaction
            self.level = 0
        if not self.enabled():
            self.level = 0
            return
        if self.level == 0:
            after = float(c.cfg.get("attention_after_minutes", 60)) * 60
            if now - c.last_user_interaction < after:
                return
        elif self.level >= 5 or now < self.next_at:
            return
        if input_idle_seconds() > AWAY_SECONDS or not c.may_initiate():
            return
        self.level += 1
        n = self.level
        prompt = (f"Ты давно не получала внимания от пользователя и просишь его откликнуться. "
                  f"Это напоминание {n} из 5, каждое настойчивее предыдущего. Скажи одну короткую фразу, "
                  f"до пятнадцати слов. Не предлагай команды.")
        text = generate(c, prompt, styled("attention", level=n))
        if n < 5:
            self.next_at = time.time() + GAPS[n - 1] * 60
        elif hasattr(c, "memory"):
            c.memory.on_ignored()  # пять раз позвала — ответа нет: отношения остывают
        log.info("Требует внимания (%d/5): %s", n, text)
        c.jobs.put(("say", text))


class PowerWatcher:
    def __init__(self, capri):
        self.capri = capri
        self.plugged = None

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="power").start()

    def _loop(self):
        while True:
            time.sleep(5)
            try:
                import psutil
                battery = psutil.sensors_battery()
                if battery is None:  # настольный ПК без батареи
                    continue
                plugged = bool(battery.power_plugged)
                if self.plugged is not None and plugged != self.plugged:
                    self._changed(plugged)
                self.plugged = plugged
            except Exception:
                log.exception("Сбой наблюдателя за зарядкой")
                time.sleep(30)

    def _changed(self, plugged):
        c = self.capri
        if not c.may_initiate():
            return
        if plugged and c.cfg.get("intimate") and c.cfg.get("adult_confirmed"):
            sound = os.path.join(c.base, "assets", "sounds", "charge.wav")  # свой файл, готового нет
            if os.path.isfile(sound):
                from voice import play_sound_async
                play_sound_async(sound)
        text = styled("charge_on" if plugged else "charge_off")
        log.info("Зарядка %s: %s", "подключена" if plugged else "отключена", text)
        c.jobs.put(("say", text))
