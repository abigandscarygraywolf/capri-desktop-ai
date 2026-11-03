"""«Живость» Капри: реакции на программы (игры, VS Code, Telegram, Discord) и на время и события
(долго сидишь за компьютером, первое приветствие за день, день рождения, возвращение после перерыва).

Программы: раз в 5 секунд смотрим, какое окно на переднем плане. Реплика — когда программа впервые
за сеанс оказалась впереди, когда долго в ней сидишь и когда закрыл игру. Включается той же галочкой
«Комментировать музыку, видео и программы» (activity_comments), уважает тихие часы и частоту уведомлений.
Время и события работают всегда, кроме выключенных уведомлений; приветствие и поздравление — раз в день.
"""
import ctypes
import datetime
import logging
import os
import random
import threading
import time

from persona import STYLE, gendered

log = logging.getLogger("capri")

# exe (в нижнем регистре) → (категория, как назвать)
APPS = {
    "code.exe": ("code", "VS Code"), "devenv.exe": ("code", "Visual Studio"), "pycharm64.exe": ("code", "PyCharm"),
    "idea64.exe": ("code", "IntelliJ IDEA"), "rider64.exe": ("code", "Rider"), "webstorm64.exe": ("code", "WebStorm"),
    "clion64.exe": ("code", "CLion"), "sublime_text.exe": ("code", "Sublime"), "cursor.exe": ("code", "Cursor"),
    "notepad++.exe": ("code", "Notepad++"), "windowsterminal.exe": ("code", "терминал"),
    "telegram.exe": ("messenger", "Telegram"), "ayugram.exe": ("messenger", "Telegram"),
    "whatsapp.exe": ("messenger", "WhatsApp"), "viber.exe": ("messenger", "Viber"),
    "discord.exe": ("discord", "Discord"), "discordcanary.exe": ("discord", "Discord"),
    "discordptb.exe": ("discord", "Discord"),
    # игры, которые узнаём по имени (остальные — по папке Steam/Epic и т. п.)
    "cs2.exe": ("game", "CS2"), "dota2.exe": ("game", "Доту"), "valorant.exe": ("game", "Валорант"),
    "valorant-win64-shipping.exe": ("game", "Валорант"), "minecraft.exe": ("game", "Майнкрафт"),
    "minecraftlauncher.exe": ("game", "Майнкрафт"), "gta5.exe": ("game", "GTA"), "rdr2.exe": ("game", "RDR 2"),
    "genshinimpact.exe": ("game", "Геншин"), "starrail.exe": ("game", "Star Rail"), "zenlesszonezero.exe": ("game", "ZZZ"),
    "fortniteclient-win64-shipping.exe": ("game", "Фортнайт"), "r5apex.exe": ("game", "Апекс"),
    "eldenring.exe": ("game", "Elden Ring"), "witcher3.exe": ("game", "Ведьмака"), "cyberpunk2077.exe": ("game", "Киберпанк"),
    "leagueclient.exe": ("game", "Лигу"), "league of legends.exe": ("game", "Лигу"), "overwatch.exe": ("game", "Овервотч"),
    "rustclient.exe": ("game", "Раст"), "pubg.exe": ("game", "PUBG"), "tslgame.exe": ("game", "PUBG"),
    "wot.exe": ("game", "Танки"), "worldoftanks.exe": ("game", "Танки"), "robloxplayerbeta.exe": ("game", "Роблокс"),
    "terraria.exe": ("game", "Террарию"), "stardew valley.exe": ("game", "Stardew Valley"),
    "baldursgate3.exe": ("game", "Baldur's Gate"), "bg3.exe": ("game", "Baldur's Gate"),
    "bg3_dx11.exe": ("game", "Baldur's Gate"), "hollow_knight.exe": ("game", "Hollow Knight"),
}
GAME_DIRS = ("steamapps\\common", "epic games", "riot games", "gog galaxy\\games", "ubisoft game launcher\\games",
             "ea games", "battle.net", "xboxgames", "games\\")
NOT_GAMES = ("launcher", "crashhandler", "unitycrashhandler", "easyanticheat", "steamwebhelper", "uninst", "setup",
             "battleye", "redist", "vc_redist", "dxsetup")

LINES = {
    "code": {
        "open": ["О, {app}. Пишешь код? Только без багов, пожалуйста.", "{app} открыт. Сейчас будет магия. Или ошибки.",
                 "Кодим? Я посижу тихо. Почти."],
        "long": ["Ты кодишь уже {h}. Глаза отдохнуть не просят?", "{h} в {app}. Сохранись и выпей воды.",
                 "{h} кода подряд. Ты [герой|героиня], но спина у тебя одна."],
    },
    "messenger": {
        "open": ["{app}? С кем переписываешься? Ладно, не моё дело.", "Опять {app}. Передавай всем привет от меня.",
                 "Переписка в {app}. Я не подглядываю, честно."],
        "long": ["Ты уже {h} в {app}. Может, позвонишь, а не пишешь?"],
    },
    "discord": {
        "open": ["Discord. Созвон с друзьями? Не забудь про меня.", "О, Discord. Только не сиди там до утра.",
                 "Discord открыт. Если позовут в игру, я пойму."],
        "long": ["{h} в Discord. Твои друзья вообще спят?"],
    },
    "game": {
        "open": ["Будешь играть в {app}? Удачи. Только не рви клавиатуру.", "Запускаешь {app}? Покажи им всем.",
                 "Идёшь в {app}? Ну всё, тебя не ждать до вечера."],
        "long": ["Ты играешь уже {h}. Может, перерыв?"],
        "close": ["[Наигрался|Наигралась] в {app}? {h}, между прочим. Как всё прошло?",
                  "Ты [играл|играла] в {app} {h}. Ну как, победа?", "[Вернулся|Вернулась] из игры. Я скучала. Немного."],
    },
}

SITTING = {
    3: ["Ты сидишь за компьютером уже три часа. Встань, разомнись, я подожду.",
        "Три часа без перерыва. Спина тебе спасибо не скажет.",
        "Три часа подряд. Сходи попей воды, а?"],
    5: ["Пять часов за компьютером. Это уже рекорд, и не самый полезный.",
        "Пять часов. Я, конечно, рада компании, но тебе пора отдохнуть."],
    8: ["Восемь часов за компьютером. Я серьёзно: сделай перерыв.",
        "Восемь часов. Даже я бы перегрелась."],
}
GREET = {
    "morning": ["Доброе утро! Как спалось?", "Утро. Кофе уже был?", "Доброе утро. Рада тебя видеть."],
    "day": ["Привет! Первый раз за сегодня видимся.", "Добрый день. Ну, рассказывай, как ты?"],
    "evening": ["Добрый вечер. Как прошёл день?", "Вечер. Наконец-то ты здесь."],
    "night": ["Ночь на дворе, а ты за компьютером. Ну привет.", "Не спится? Привет."],
}
GREET_STYLE = {
    "soft": {"morning": ["Доброе утро! Надеюсь, ты [выспался|выспалась]. Я рядом весь день."]},
    "sarcastic": {"morning": ["Доброе утро. Мир всё ещё стоит, ты всё ещё здесь. Чудеса."]},
    "calm": {"morning": ["Доброе утро. Спокойного дня."]},
    "bold": {"morning": ["Подъём, соня! Новый день, новые баги."]},
}
RETURN = ["Ты где [пропадал|пропадала] {d}? Я тут одна сидела.", "{D} тебя не было. Я считала.",
          "О, явление. {D} без тебя, между прочим."]
RETURN_SOFT = ["{D} тебя не было. Я скучала. Хорошо, что ты [вернулся|вернулась]."]
BIRTHDAY = ["С днём рождения, {name}! Сегодня тебе можно всё. Ну, почти всё.",
            "С днём рождения! Я подготовила самое ценное, что у меня есть: себя. И поздравления.",
            "Сегодня твой день рождения! Пусть всё компилируется с первого раза и музыка не надоедает."]


def plural_hours(h):
    h = int(h)
    if h % 10 == 1 and h % 100 != 11:
        return f"{h} час"
    if 2 <= h % 10 <= 4 and not 12 <= h % 100 <= 14:
        return f"{h} часа"
    return f"{h} часов"


def plural_days(d):
    if d % 10 == 1 and d % 100 != 11:
        return f"{d} день"
    if 2 <= d % 10 <= 4 and not 12 <= d % 100 <= 14:
        return f"{d} дня"
    return f"{d} дней"


def duration_words(seconds):
    m = int(seconds // 60)
    if m < 60:
        if m % 10 == 1 and m % 100 != 11:
            return f"{m} минуту"
        if 2 <= m % 10 <= 4 and not 12 <= m % 100 <= 14:
            return f"{m} минуты"
        return f"{m} минут"
    h, rest = divmod(m, 60)
    if 20 <= rest <= 40:
        return "полтора часа" if h == 1 else f"{h} с половиной часа"
    return plural_hours(h + 1 if rest > 40 else h)


def foreground_exe():
    """(имя exe в нижнем регистре, полный путь) программы на переднем плане или (None, None)."""
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None, None
        import psutil
        p = psutil.Process(pid.value)
        path = p.exe() or ""
        return (p.name() or "").lower(), path.lower()
    except Exception:
        return None, None


def classify(exe, path):
    if not exe:
        return None
    if exe in APPS:
        return APPS[exe]
    if any(bad in exe for bad in NOT_GAMES):
        return None
    for d in GAME_DIRS:
        i = path.find(d) if path else -1
        if i >= 0:
            rest = path[i + len(d):].strip("\\").split("\\")
            folder = rest[0] if len(rest) > 1 and rest[0] else ""
            # папка игры («hades», «dota 2 beta») — как название; слишком длинное — просто «игру»
            name = folder.replace(" beta", "").title() if folder and len(folder) < 25 else "игру"
            return ("game", name)
    return None


class Life:
    def __init__(self, capri):
        self.capri = capri
        self.seen = set()             # категории/программы, о которых уже сказали в этом сеансе
        self.current = None           # (категория, название) на переднем плане
        self.since = 0.0              # с какого времени на переднем плане
        self.long_said = set()
        self.game = None              # (название, время запуска) — пока игра открыта
        self.last_comment = 0.0
        self.session_start = time.time()
        self.sitting_said = set()
        self.pending = []             # реплики, ждущие, когда можно говорить: (текст, до какого времени)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="life").start()

    # ----- общие проверки -----
    def _apps_enabled(self):
        return bool(self.capri.cfg.get("activity_comments", False))

    def _gap(self):
        factor = self.capri.cooldown_factor() if hasattr(self.capri, "cooldown_factor") else 1.0
        return float(self.capri.cfg.get("activity_cooldown_minutes", 8)) * 60 * factor

    def _queue(self, text, ttl=180):
        if text:
            self.pending.append((text, time.time() + ttl))

    def _flush(self):
        now = time.time()
        self.pending = [(t, until) for t, until in self.pending if until > now]
        if not self.pending or not self.capri.may_initiate():
            return
        text, _ = self.pending.pop(0)
        self.last_comment = now
        log.info("Живость: %s", text)
        self.capri.jobs.put(("say", text))

    @staticmethod
    def _say(variants, **kw):
        return gendered(random.choice(variants)).format(**kw)

    # ----- программы -----
    def _apps(self):
        exe, path = foreground_exe()
        kind = classify(exe, path)
        now = time.time()
        # игра закрыта (её больше нет среди процессов)
        if self.game and (kind is None or kind[0] != "game" or kind[1] != self.game[0]):
            if not self._process_alive(self.game[2]):
                name, started, _ = self.game
                self.game = None
                played = now - started
                if played > 10 * 60 and now - self.last_comment > 60:
                    if hasattr(self.capri, "achv"):
                        self.capri.award(self.capri.achv.on_event("game", minutes=played / 60))
                    h = duration_words(played)
                    self._queue(self._say(LINES["game"]["close"], app=name, h=h).replace(
                        "? " + h + ",", "? " + h[:1].upper() + h[1:] + ","))
        if kind != self.current:
            self.current, self.since = kind, now
        if not kind:
            return
        cat, name = kind
        if cat == "game" and not self.game:
            self.game = (name, now, exe)
        key = cat + ":" + name
        if key not in self.seen and now - self.since > 6:  # продержалась на переднем плане пару опросов
            self.seen.add(key)
            if now - self.last_comment > min(self._gap(), 300) and random.random() < 0.7:
                self._queue(self._say(LINES[cat]["open"], app=name), ttl=60)
        hours = (now - self.since) / 3600
        long_after = 1.0 if cat == "messenger" else 2.0
        mark = key + ":" + str(int(hours // long_after))
        if hours >= long_after and mark not in self.long_said:
            self.long_said.add(mark)
            self._queue(self._say(LINES[cat]["long"], app=name, h=plural_hours(hours)))

    @staticmethod
    def _process_alive(exe):
        try:
            import psutil
            return any((p.info.get("name") or "").lower() == exe for p in psutil.process_iter(["name"]))
        except Exception:
            return True

    # ----- время и события -----
    def _sitting(self):
        """Сколько непрерывно сидишь за ПК: отход больше чем на 10 минут сбрасывает отсчёт."""
        from presence import input_idle_seconds
        if input_idle_seconds() > 600:
            self.session_start = time.time()
            self.sitting_said.clear()
            return
        hours = (time.time() - self.session_start) / 3600
        for mark in (8, 5, 3):
            if hours >= mark and mark not in self.sitting_said:
                self.sitting_said.update(m for m in (3, 5, 8) if m <= mark)
                if hasattr(self.capri, "achv"):
                    self.capri.award(self.capri.achv.on_event("sitting", hours=mark))
                self._queue(self._say(SITTING[mark]), ttl=1800)
                break

    def greeting(self, startup=False):
        """Приветствие первого раза за день (с поздравлением в день рождения и упрёком после долгого
        отсутствия). None — если сегодня уже здоровались."""
        c = self.capri
        profile = c.profiles.active()
        today = datetime.date.today()
        if profile.get("last_greet") == today.isoformat():
            return None
        profile["last_greet"] = today.isoformat()
        days = c.memory.apply_absence() if hasattr(c, "memory") else 0
        c.profiles.save()
        parts = []
        h = datetime.datetime.now().hour
        part = "morning" if 5 <= h < 12 else "day" if h < 18 else "evening" if h < 23 else "night"
        styled = GREET_STYLE.get(STYLE["character"], {}).get(part)
        parts.append(self._say(styled if styled and random.random() < 0.5 else GREET[part]))
        if days >= 2:
            pool = RETURN_SOFT if STYLE["character"] == "soft" else RETURN
            w = plural_days(days)
            parts = [self._say(pool, d=w, D=w[:1].upper() + w[1:])]
        bd = profile.get("birthday")
        if bd and bd == today.strftime("%d.%m"):
            from persona import USER
            parts.append(self._say(BIRTHDAY, name=USER["name"] or "чумба"))
            if hasattr(c, "memory"):
                c.memory._change(5, "день рождения")
            if hasattr(c, "achv"):
                c.award(c.achv.on_event("birthday"))
        return " ".join(parts)

    def _daily(self):
        """Компьютер не выключали на ночь: новый день — здороваемся, когда пользователь за ПК."""
        from presence import input_idle_seconds
        if self.capri.profiles.active().get("last_greet") == datetime.date.today().isoformat():
            return
        if input_idle_seconds() < 60 and self.capri.may_initiate():
            text = self.greeting()
            if text:
                self.capri.jobs.put(("say", text))

    def _loop(self):
        tick = 0
        while True:
            time.sleep(5)
            tick += 1
            try:
                if self.capri.effective_level() == "off":
                    self.pending.clear()
                    continue
                if self._apps_enabled():
                    self._apps()
                if tick % 12 == 0:  # раз в минуту
                    self._sitting()
                    self._daily()
                self._flush()
            except Exception:
                log.exception("Сбой «живости»")
                time.sleep(30)
