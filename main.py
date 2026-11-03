"""Капри — голосовой ассистент для Windows.
Запуск: run.bat (или pythonw main.py)."""
import json
import logging
import os
import queue
import random
import re
import sys
import tempfile
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")

# журнал — до всех библиотек: если какой-то не хватает, Капри падает без окна, и узнать причину можно только тут
logging.basicConfig(filename=os.path.join(BASE, "capri.log"), level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("capri")
log.info("Python %s", sys.version.split()[0])


def fatal(text):
    """Капри запускается без окна консоли, поэтому о том, что не так, говорим окном Windows."""
    log.error(text)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Капри не запустилась", 0x10)
    except Exception:
        pass
    sys.exit(1)


try:
    from PySide6.QtCore import QObject, Qt, Signal, QTimer
    from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QLabel, QMenu, QSlider,
                                   QSystemTrayIcon, QWidget, QWidgetAction)

    from actions import CAPRI_URL, Actions, Reply
    from ai import make_ai
    from local_ai import LocalAI
    from persona import LINES, gendered, line, set_style, set_user, styled
    from avatar import Avatar
    import zapret
    from voice import (Listener, Speaker, default_input_name, google_stt, input_devices, make_glitch_sound,
                       play_sound_async)
except ImportError as e:
    log.exception("Не хватает библиотек")
    fatal(f"Не установлены нужные библиотеки ({e.name or e}).\n\n"
          f"Запусти setup.bat в папке Капри и дождись надписи «Готово», потом снова run.bat.\n"
          f"Если setup.bat выдаёт ошибку — сфотографируй его окно.\n\nPython {sys.version.split()[0]}")

DEFAULTS = {
    "enable_ai": False,
    "local_ai": True,
    "local_model": "qwen3:8b",
    "barge_in": True,
    "mic_device": None,
    "chatter": True,
    # настройки из окна «Настройки Капри» хранятся в профиле пользователя (profiles.json), это значения по умолчанию
    "character": "bold",              # bold / soft / sarcastic / calm
    "notify_level": "normal",         # off / rare / normal / often / unlimited — как часто пишет сама
    "needs_attention": True,          # серия всё более настойчивых реплик, если давно не обращались
    "attention_after_minutes": 60,    # через сколько минут без обращения начинается серия
    "swearing": False,                # мат (18+)
    "intimate": False,                # интимный режим (18+)
    "adult_confirmed": False,         # подтверждение, что пользователю есть 18
    "quiet_from": "23:00",            # тихие часы: сама не появляется и не комментирует
    "quiet_to": "09:00",
    "activity_comments": False,       # комментировать Spotify и YouTube (галочка в трее)
    "activity_cooldown_minutes": 8,   # не чаще одной реплики на смену трека/видео раз в столько минут
    "activity_music_chance": 0.35,    # шанс реплики при смене трека (начало музыки/видео — почти всегда)
    "activity_use_cloud": False,      # True: названия треков и видео уходят в Claude для реплик (нужен ключ)
    "chatter_min_minutes": 15,
    "chatter_max_minutes": 40,
    "roam_chance": 0.5,
    "teleport_on_answer": True,
    "search_when_unsure": True,
    "voice_volume": 100,     # громкость голоса Капри 0..100 (общая громкость Windows не меняется)
    "mic_gain": 1.0,         # громкость микрофона для Капри: 1 — как есть, 2 — вдвое громче
    "mic_sensitivity": 100,  # 100 — слышит всё; меньше — тихий шум и фон отбрасываются
    "user_name_mode": "none",  # как называть пользователя: "custom" — user_name, "windows" — имя пользователя
                               # Windows, "pc" — имя компьютера, "none" — не называть
    "user_name": "",
    "user_gender": "male",     # "male" / "female" — в каком роде Капри к тебе обращается
    "browser": "",
    "replies": {},           # свои ответы: {"фраза": "что ответит Капри"} — проверяются раньше команд и нейросети  # в каком браузере открывать сайты: "хром", "яндекс", "опера"… или путь к exe; "" — как в Windows
    "anthropic_api_key": "",
    # облачная нейросеть: "anthropic" (Claude по ключу выше) или "openai_compatible" (OrcaRouter и др.)
    "ai_provider": "anthropic",
    "ai_base_url": "https://api.orcarouter.ai/v1",
    "ai_api_key": "",                 # ключ OrcaRouter: sk-orca-…
    "ai_model": "orcarouter/auto",    # или конкретная: anthropic/claude-sonnet-5, openai/gpt-5.5 …
    "ai_timeout_seconds": 60,
    "model": "claude-opus-5-5",
    "wake_words": ["капри", "каприз", "капре", "кепри", "капли"],
    "use_google_stt": True,
    "voice": "ru-RU-SvetlanaNeural",
    "tts_engine": "edge",
    "voice_rate": "+10%",
    "voice_pitch": "+15Hz",
    "voice_shift": 0,
    "voice_lively": False,
    "voice_fx": 1.8,
    "listen_window_seconds": 8,
    "followup_seconds": 6,
    "hide_after_seconds": 12,
    "greet_on_start": True,
    "vosk_model": "models/vosk-model-small-ru-0.22",
    "sites": {
        "ютуб": "https://www.youtube.com", "youtube": "https://www.youtube.com",
        "гугл": "https://www.google.com", "google": "https://www.google.com",
        "яндекс": "https://ya.ru", "вк": "https://vk.com", "вконтакте": "https://vk.com",
        "почту": "https://mail.google.com", "почта": "https://mail.google.com",
        "гитхаб": "https://github.com", "твич": "https://www.twitch.tv",
        "википедию": "https://ru.wikipedia.org", "википедия": "https://ru.wikipedia.org",
        "переводчик": "https://translate.google.com", "карты": "https://yandex.ru/maps",
        "погоду": "https://yandex.ru/pogoda", "chatgpt": "https://chatgpt.com",
        "клод": "https://claude.ai", "кинопоиск": "https://www.kinopoisk.ru",
        "авито": "https://www.avito.ru", "озон": "https://www.ozon.ru",
        "вайлдберриз": "https://www.wildberries.ru"
    },
    "apps": {
        "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer",
        "диспетчер задач": "taskmgr", "параметры": "ms-settings:", "настройки": "ms-settings:",
        "панель управления": "control", "командную строку": "cmd", "командная строка": "cmd",
        "терминал": "wt", "пейнт": "mspaint", "paint": "mspaint", "ворд": "winword",
        "эксель": "excel", "браузер": "https://www.google.com",
        "настройки звука": "ms-settings:sound", "настройки экрана": "ms-settings:display",
        "корзину": "shell:RecycleBinFolder", "загрузки": "shell:Downloads"
    },
    "app_aliases": {
        "хром": "chrome", "гугл хром": "google chrome", "стим": "steam", "дискорд": "discord",
        "телеграм": "telegram", "телеграмм": "telegram", "спотифай": "spotify",
        "опера": "opera", "яндекс браузер": "yandex", "вс код": "visual studio code",
        "визуал студио код": "visual studio code", "обс": "obs", "эпик геймс": "epic games",
        "ватсап": "whatsapp", "зум": "zoom", "фотошоп": "photoshop", "майнкрафт": "minecraft"
    }
}


def _config_blank():
    """config.json нет или он пустой (всё стёрли) — такой можно спокойно создать заново."""
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            return not f.read().strip()
    except FileNotFoundError:
        return True


def _edit_config(change):
    """Прочитать config.json, применить change(data) и записать. Файл с ошибкой не перезаписываем —
    иначе пропадут правки пользователя. Возвращает текст ошибки или None."""
    try:
        if _config_blank():
            data = {}
        else:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:  # Блокнот иногда сохраняет с BOM
                data = json.load(f)
    except Exception:
        log.exception("config.json с ошибкой, не записываю")
        return "в config.json ошибка. Исправь её или удали файл, он создастся заново."
    change(data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return None


def save_setting(key, value):
    """Записать одну настройку в config.json, не трогая остальные."""
    _edit_config(lambda data: data.__setitem__(key, value))


def save_entry(section, name, value):
    """Свой сайт или программа: section "sites"/"apps". value=None — убрать; встроенные записи
    убираются пометкой null, иначе вернулись бы из настроек по умолчанию."""
    def change(data):
        entries = data.setdefault(section, {})
        if value is None and name not in DEFAULTS.get(section, {}):
            entries.pop(name, None)
        else:
            entries[name] = value
    return _edit_config(change)


def user_display_name(cfg):
    """Как Капри называет пользователя — по настройке user_name_mode."""
    mode = cfg.get("user_name_mode", "none")
    if mode == "custom":
        return cfg.get("user_name", "").strip()
    if mode == "windows":
        return os.environ.get("USERNAME", "")
    if mode == "pc":
        return os.environ.get("COMPUTERNAME", "")
    return ""


def apply_user(cfg):
    set_user(user_display_name(cfg), cfg.get("user_gender", "male"))


from ai import FRESH as FRESH_RE  # вопросы про свежие данные (погода, курсы, новости)

PROFILE_KEYS = ("character", "notify_level", "needs_attention", "attention_after_minutes", "swearing",
                "intimate", "adult_confirmed", "quiet_from", "quiet_to")
LEVEL_RANGES = {  # как часто Капри появляется сама: (от, до) минут между репликами
    "rare": (60, 120), "normal": (20, 45), "often": (8, 20), "unlimited": (3, 8),
}
LEVEL_COOLDOWN = {"rare": 2.0, "normal": 1.0, "often": 0.6, "unlimited": 0.3}  # множитель паузы комментариев к музыке

CONFIG_ERROR = ""  # что сказать вслух, если config.json не прочитался


def load_config():
    global CONFIG_ERROR
    CONFIG_ERROR = ""
    cfg = json.loads(json.dumps(DEFAULTS))
    if not _config_blank():
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    for name, value in v.items():  # null — убранная встроенная запись
                        if value is None:
                            cfg[k].pop(name, None)
                        else:
                            cfg[k][name] = value
                else:
                    cfg[k] = v
            missing = [k for k in DEFAULTS if k not in user]
            if missing:  # файл неполный (его создал setup_ai.bat или он из старой версии) — дописываем
                _edit_config(lambda data: [data.setdefault(k, DEFAULTS[k]) for k in missing])
                log.info("В config.json добавлены недостающие настройки: %s", ", ".join(missing))
        except json.JSONDecodeError as e:
            log.error("config.json с ошибкой (строка %d, символ %d: %s), использую настройки по умолчанию",
                      e.lineno, e.colno, e.msg)
            CONFIG_ERROR = (f"В config.json ошибка в строке {e.lineno}, я его не прочитала и работаю "
                            "со стандартными настройками. Проверь там кавычки, запятые и двойные слеши в путях.")
        except Exception:
            log.exception("config.json не прочитался, использую настройки по умолчанию")
            CONFIG_ERROR = "Не смогла прочитать config.json, работаю со стандартными настройками."
    else:  # файла нет или его содержимое стёрли — создаём заново со стандартными настройками
        log.info("config.json пустой или удалён, создаю заново")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
    return cfg


STOP_RE = re.compile(r"\b(стоп|хватит|молчи|замолчи|помолчи|достаточно|подожди|остановись|перестань|"
                     r"заткнись|умолкни)\b")


def fullscreen_app_active():
    """Открыта игра или видео на весь экран — тогда не лезем со спонтанными репликами."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return False
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False  # рабочий стол
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        return (r.right - r.left) >= u.GetSystemMetrics(0) and (r.bottom - r.top) >= u.GetSystemMetrics(1)
    except Exception:
        return False


class Capri(QObject):
    text_reply = Signal(str)
    chat_started = Signal()        # окно чата: «Капри думает…» (и сброс набежавшего текста)
    chat_delta = Signal(str)       # кусочек ответа по мере генерации
    chat_finished = Signal(str)    # итоговый ответ
    chat_note = Signal(str)        # служебная пометка (нет связи с нейросетью и т. п.)
    chat_award = Signal(str)       # 🏆 новое достижение или уровень
    role_changed = Signal(str)     # включён ролевой режим ('' — обычный разговор)
    summon = Signal()
    vanish = Signal()
    mode = Signal(str, float)
    subtitle = Signal(str)
    quit_app = Signal()
    anim = Signal(str)
    roam = Signal()
    hop = Signal()
    move_to = Signal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.base = BASE
        self.last_user_interaction = time.time()
        self.last_pet = 0.0
        from profiles_store import Profiles
        from memory import Memory
        from chat_history import ChatHistory
        self.profiles = Profiles()
        from achievements import Achievements
        from roles import Roles
        self.memory = Memory(self)     # факты о пользователе и шкала отношений (в профиле)
        self.achv = Achievements(self) # достижения и уровни (в профиле)
        self.roles = Roles(self)       # сказка, английский, друг, тренер, квест
        self.history = ChatHistory()   # переписка в окне чата, у каждого профиля своя
        self.chat_cancel = False
        self._ai_note = ("", 0.0)
        self._apply_active_profile()
        words = sorted(cfg["wake_words"], key=len, reverse=True)
        self.wake_re = re.compile(r"(^|\s)(" + "|".join(map(re.escape, words)) + r")(?=\s|$|[,.!?])",
                                  re.IGNORECASE)
        self.ai = make_ai(cfg)
        self.local = LocalAI(cfg) if cfg.get("local_ai") else None
        from chat_lite import LiteChat
        self.lite = LiteChat()  # встроенная болтовня: работает без Ollama и ключей
        if self.local:
            self.local.on_model_change = self._remember_model
        self._restore_context()
        self.actions = Actions(cfg, BASE, self.ai, save=save_entry)
        self.config_mtime = self._config_mtime()
        self.zapret_checked = False  # предлагали ли уже исправить zapret в этом сеансе
        self.actions.local = self.local
        self.speaker = Speaker(cfg)
        self.jobs = queue.Queue()
        self.awake_until = 0.0
        self.last_partial_wake = 0.0
        self.speaking = False
        self.interrupted = False
        self.speech_words = set()
        self.speech_end = 0.0
        self.last_activity = time.time()
        self.recent_chatter = []
        self.listener = None
        self.glitch_wav = os.path.join(tempfile.gettempdir(), "capri_glitch.wav")
        try:
            make_glitch_sound(self.glitch_wav, self.speaker.volume)
        except Exception:
            self.glitch_wav = None

    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()
        if self.local:
            threading.Thread(target=self.local.start_server, daemon=True).start()
        from activity import ActivityWatcher
        self.activity = ActivityWatcher(self, fullscreen_app_active)
        self.activity.start()
        from presence import AttentionWatcher, PowerWatcher
        AttentionWatcher(self).start()
        PowerWatcher(self).start()
        from life import Life
        self.life = Life(self)   # программы (игры, VS Code, Telegram, Discord), «сидишь три часа», приветствия
        self.life.start()
        model =os.path.join(BASE, self.cfg["vosk_model"])
        if os.path.isdir(model):
            self.listener = Listener(model, self.on_final, self.on_partial, self.on_listener_error,
                                     device_name=self.cfg.get("mic_device") or None,
                                     gain=float(self.cfg.get("mic_gain", 1.0)),
                                     sensitivity=int(self.cfg.get("mic_sensitivity", 100)))
            self.listener.start()
        else:
            self.jobs.put(("say", line("no_model")))
            return
        # вступление: анимация capri + приветствие
        greeting = ""
        if self.cfg.get("greet_on_start"):
            # первый запуск за день — «доброе утро», поздравление в день рождения, «где ты пропадал»
            greeting = self.life.greeting(startup=True) or line("greet")
        self.jobs.put(("say", greeting, "capri"))
        if CONFIG_ERROR:
            self.jobs.put(("say", CONFIG_ERROR))
        threading.Thread(target=self._chatter_loop, daemon=True).start()  # сам проверяет, включено ли
        threading.Thread(target=self._prewarm_voice, daemon=True).start()

    def _prewarm_voice(self):
        """Через полминуты после запуска озвучиваем в фоне постоянные фразы и свои ответы — потом они
        звучат сразу, без ожидания сервера Microsoft."""
        time.sleep(30)
        static = [gendered(t) for variants in LINES.values() for t in variants if "{" not in t]
        static += list(self.cfg.get("replies", {}).values())
        self.speaker.prewarm(static)

    # ----- спонтанные появления -----
    def _chatter_loop(self):
        def next_delay():
            lo, hi = self.notify_range()
            return random.uniform(lo, max(lo, hi)) * 60
        due = time.time() + next_delay()
        while True:
            time.sleep(15)
            now = time.time()
            if self.effective_level() == "off":  # выключено в трее или в настройках — ждём, отсчёт начнётся заново
                due = now + next_delay()
                continue
            if now < due:
                continue
            quiet = now - self.last_activity > 120 and self.jobs.empty() and not self.speaking
            if quiet and self.may_initiate():
                self.jobs.put(("chatter",))
                due = now + next_delay()
            else:
                due = now + 60  # занят или в игре/фильме — попробуем позже

    def chatter_line(self):
        hour = time.localtime().tm_hour
        text = None
        if 0 <= hour < 5 and random.random() < 0.5:
            text = line("chatter_night")
        elif 6 <= hour < 11 and random.random() < 0.3:
            text = line("chatter_morning")
        elif self.local and random.random() < 0.4:
            text = self.local.chatter()
        if not text:
            from memory import fact_line, hurt_line
            mood = self.memory.level()[0]
            fact = self.memory.random_fact()
            if mood == "hurt" and random.random() < 0.6:
                text = hurt_line()
            elif fact and random.random() < 0.2:
                text = fact_line(fact)
        for _ in range(5):
            if text and text not in self.recent_chatter:
                break
            text = styled("chatter", avoid=text)
        self.recent_chatter = (self.recent_chatter + [text])[-6:]
        return text

    # ----- события микрофона (поток слушателя) -----
    def has_wake(self, text):
        return bool(self.wake_re.search(text.lower()))

    def strip_wake(self, text):
        t = text.lower()
        last = None
        for last in self.wake_re.finditer(t):
            pass
        if last and t[last.end():].strip(" ,.!?"):
            t = t[last.end():]  # берём то, что сказано после имени (до него могло быть эхо)
        t = self.wake_re.sub(" ", t)
        return re.sub(r"^[\s,.!?]+|[\s,.!?]+$", "", t)

    def appear(self, seconds):
        if self.glitch_wav:
            play_sound_async(self.glitch_wav)
        self.summon.emit()
        self.mode.emit("listening", float(seconds))

    # ----- перебивание -----
    def is_echo(self, text):
        """Микрофон слышит голос самой Капри: все слова фразы есть в том, что она говорит."""
        words = text.lower().replace("ё", "е").split()
        return bool(words) and all(w in self.speech_words for w in words)

    def wants_interrupt(self, text):
        t = text.lower()
        return (self.has_wake(t) or STOP_RE.search(t)) and not self.is_echo(t)

    def interrupt(self):
        if not self.speaking or self.interrupted:
            return
        self.interrupted = True
        self.speaker.stop()
        self.awake_until = time.time() + self.cfg["listen_window_seconds"]
        self.mode.emit("listening", float(self.cfg["listen_window_seconds"]))
        self.subtitle.emit(line("listen"))
        log.info("Капри перебили")

    def on_partial(self, text):
        now = time.time()
        if self.speaking:
            if self.cfg.get("barge_in") and self.wants_interrupt(text):
                self.interrupt()
            return
        if now - self.last_partial_wake > 3 and now > self.awake_until and self.has_wake(text):
            self.last_partial_wake = now
            self.appear(self.cfg["listen_window_seconds"])

    def on_final(self, text, audio):
        now = time.time()
        if self.actions.autoscroll_active() and STOP_RE.search(text.lower()) and not self.is_echo(text):
            # во время автопрокрутки «стоп» слышим и без имени
            self.actions.stop_background()
            self.subtitle.emit(line("scroll_stop"))
            return
        if self.speaking and not self.interrupted:
            if not (self.cfg.get("barge_in") and self.wants_interrupt(text)):
                return  # эхо собственной речи
            self.interrupt()
        if now - self.speech_end < 1.0 and self.is_echo(text):
            return
        woke = self.has_wake(text)
        if not woke and now > self.awake_until:
            return
        cmd = self.strip_wake(text) if woke else text
        if STOP_RE.match(cmd.strip()) and len(cmd.split()) <= 3:
            # «Капри, стоп» — замолчать, остановить автопрокрутку и слушать дальше
            self.awake_until = now + self.cfg["listen_window_seconds"]
            if self.actions.stop_background():
                self.subtitle.emit(line("scroll_stop"))
            return
        if len(cmd) < 2:
            self.awake_until = now + self.cfg["listen_window_seconds"]
            self.subtitle.emit("")
            if now - self.last_partial_wake > 3:
                self.appear(self.cfg["listen_window_seconds"])
            return
        self.awake_until = 0
        self.jobs.put(("voice", cmd, audio, woke))

    def on_listener_error(self, err, kind="mic"):
        self.jobs.put(("say", line("model_broken" if kind == "model" else "no_mic")))

    def _apply_active_profile(self):
        p = self.profiles.active()
        self.cfg['user_name_mode'] = 'custom'
        self.cfg['user_name'] = p['name']
        self.cfg['user_gender'] = p['gender']
        apply_user(self.cfg)
        saved = p.get('settings', {})
        for key in PROFILE_KEYS:  # настройки профиля; чего в профиле нет — значение по умолчанию
            self.cfg[key] = saved.get(key, DEFAULTS[key])
        adult = bool(self.cfg['adult_confirmed'])
        set_style(self.cfg['character'], self.cfg['swearing'] and adult, self.cfg['intimate'] and adult)
        if hasattr(self, 'memory'):
            self.memory.push_context()

    def _restore_context(self):
        """Последние реплики чата этого профиля — нейросетям как контекст (разговор продолжается после перезапуска)."""
        ctx = self.history.context(self.profiles.active()['id'])
        self.ai.history = list(ctx)
        if self.local:
            self.local.history = list(ctx[-6:])

    def switch_profile(self, profile_id):
        self.profiles.select(profile_id)
        self._apply_active_profile()
        # Do not leak conversational history between users.
        self.ai.history.clear()
        if self.local:
            self.local.history.clear()
        self.roles.exit(silent=True)
        self._restore_context()
        self.text_reply.emit('Активный профиль: ' + self.profiles.active()['name'])

    def set_profile(self, mode, name, gender):
        """«Как ко мне обращаться…»: как называть пользователя и в каком роде. Сразу и запоминается."""
        for key, value in (("user_name_mode", mode), ("user_name", name), ("user_gender", gender)):
            self.cfg[key] = value
            save_setting(key, value)
        apply_user(self.cfg)
        log.info("Обращение: %s, %s", user_display_name(self.cfg) or "без имени", gender)

    # ----- настройки: уведомления, тихие часы -----
    def effective_level(self):
        """off — если выключена галочка «Появляться самой» или выбран уровень «Выкл»."""
        if not self.cfg.get("chatter", True):
            return "off"
        level = self.cfg.get("notify_level", "normal")
        return level if level in LEVEL_RANGES else ("off" if level == "off" else "normal")

    def notify_range(self):
        return LEVEL_RANGES.get(self.effective_level(), LEVEL_RANGES["normal"])

    def cooldown_factor(self):
        return LEVEL_COOLDOWN.get(self.effective_level(), 1.0)

    @staticmethod
    def _minutes(text, default):
        try:
            h, m = str(text).split(":")
            return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return default

    def in_quiet_hours(self, now=None):
        """Тихие часы (с — до), в том числе через полночь: 23:00–09:00. Одинаковые «с» и «до» — тихих часов нет."""
        t = time.localtime(now)
        cur = t.tm_hour * 60 + t.tm_min
        a = self._minutes(self.cfg.get("quiet_from"), 23 * 60)
        b = self._minutes(self.cfg.get("quiet_to"), 9 * 60)
        if a == b:
            return False
        return (a <= cur < b) if a < b else (cur >= a or cur < b)

    def may_initiate(self):
        """Можно ли Капри самой сказать что-то: не тихие часы, не игра или видео на весь экран, не занята."""
        return (not self.in_quiet_hours() and not fullscreen_app_active() and not self.speaking
                and self.jobs.empty() and time.time() > self.awake_until)

    def update_settings(self, **values):
        """Сохранить настройки в активный профиль и применить сразу."""
        self.profiles.update_settings(values)
        self._apply_active_profile()

    def set_notify_level(self, level):
        if level == "off":
            self.set_chatter(False)
        else:
            self.set_chatter(True)
            self.update_settings(notify_level=level)

    def test_notification(self):
        """Тестовая реплика с текущими настройками (тихие часы не мешают)."""
        self.jobs.put(("say", self.chatter_line()))

    def on_pet(self):
        """Поглаживание аватара мышью."""
        now = time.time()
        if now - self.last_pet < 25 or self.speaking or not self.jobs.empty():
            return
        self.last_pet = now
        self.last_user_interaction = now
        self.jobs.put(("say", styled("touch")))
        change = self.memory.on_pet()
        if change:
            self.jobs.put(("say", change))
        self.award(self.achv.on_pet())

    def set_chatter(self, on):
        """Галочка в трее: появляется ли Капри сама (поболтать, погулять по экрану). Сразу и запоминается."""
        self.cfg["chatter"] = bool(on)
        save_setting("chatter", bool(on))
        log.info("Самостоятельные появления: %s", "включены" if on else "выключены")

    # ----- достижения, роли -----
    def award(self, lines):
        """Объявить новые достижения: строка 🏆 в окне чата (и в истории) и голос."""
        for text in lines or []:
            self.history.add(self.profiles.active()["id"], "ach", text)
            self.chat_award.emit(text)
            self.jobs.put(("say", text))

    def has_brain(self):
        """Есть ли чем отвечать на свободные темы: облако (OrcaRouter, Claude) или Ollama."""
        if self.cfg.get("enable_ai") and self.ai.available:
            return True
        return bool(self.local and self.local.running())

    def clear_context(self):
        self.ai.history.clear()
        if self.local:
            self.local.history.clear()

    def set_role(self, key):
        """Выбор роли в окне чата. Реплика-открытие показывается в чате и озвучивается."""
        text = self.roles.set(key)
        if text:
            self.text_reply.emit(text)
            if self.roles.speak() or not key:
                self.jobs.put(("say", text))

    # ----- чат: ответ с потоковым выводом -----
    def chat_answer(self, cmd):
        """Ответ для окна чата: облако → Ollama → встроенная болтовня. Текст идёт в окно по кусочкам."""
        def delta(piece):
            if self.chat_cancel:
                return False
            self.chat_delta.emit(piece)
            return True

        answer = None
        if self.cfg.get("enable_ai") and self.ai.available:
            try:
                answer = self.ai.ask(cmd, on_delta=delta)
                if getattr(self.ai, "failed", False):
                    self._note_ai_problem(answer)
                    answer = None
            except Exception:
                log.exception("Ошибка облачной нейросети в чате")
                answer = None
        if not answer and not self.chat_cancel and self.local:
            self.chat_started.emit()  # стираем то, что успело набежать от облака
            try:
                answer = self.local.ask(cmd, on_delta=delta)
            except Exception:
                log.exception("Ошибка локальной нейросети в чате")
                answer = None
        if not answer:
            # ни облака, ни Ollama: встроенная болтовня, чат не молчит и не ломается
            answer = self.lite.reply(cmd)
        return answer

    def _note_ai_problem(self, text):
        """Пометка в чате, почему облако не ответило (одна и та же — не чаще раза в 10 минут)."""
        last, when = self._ai_note
        if text != last or time.time() - when > 600:
            self._ai_note = (text, time.time())
            self.chat_note.emit(text + " Отвечаю без облака.")

    def stop_chat(self):
        """Кнопка «Остановить» в окне чата: обрывает генерацию и речь."""
        self.chat_cancel = True
        self.interrupt()

    def clear_chat(self):
        pid = self.profiles.active()["id"]
        self.history.clear(pid)
        self.ai.history.clear()
        if self.local:
            self.local.history.clear()

    def set_activity(self, on):
        """Галочка в трее: комментировать ли Spotify и YouTube. Сразу и запоминается."""
        self.cfg["activity_comments"] = bool(on)
        save_setting("activity_comments", bool(on))
        log.info("Комментарии к музыке и видео: %s", "включены" if on else "выключены")

    def set_search_when_unsure(self, on):
        """Галочка в трее: открывать ли Google, когда Капри не знает ответа. Сразу и запоминается."""
        self.cfg["search_when_unsure"] = bool(on)
        save_setting("search_when_unsure", bool(on))
        log.info("Поиск в браузере, если не знаю: %s", "включён" if on else "выключен")

    def _remember_model(self, name):
        """Ollama нашла другую скачанную модель — записываем её, чтобы не искать при каждом запуске."""
        self.cfg["local_model"] = name
        save_setting("local_model", name)

    # ----- config.json на лету -----
    @staticmethod
    def _config_mtime():
        try:
            return os.path.getmtime(CONFIG_PATH)
        except OSError:
            return None

    def reload_config_if_changed(self, speak=True):
        """Правки config.json (сайты, программы, названия) подхватываются без перезапуска.
        speak=False — из окна в трее: там говорить нельзя (речь блокирует окно)."""
        mtime = self._config_mtime()
        if mtime == self.config_mtime:
            return
        fresh = load_config()
        if CONFIG_ERROR:  # с ошибкой — работаем как было и говорим, где ошибка
            if speak:
                self.config_mtime = mtime
                self.say(CONFIG_ERROR)
            return
        self.config_mtime = mtime
        for key in ("sites", "apps", "app_aliases", "search_when_unsure", "browser", "chatter", "replies",
                    "activity_comments", "activity_cooldown_minutes", "activity_music_chance", "activity_use_cloud",
                    "user_name_mode", "user_name", "user_gender"):
            self.cfg[key] = fresh[key]
        ai_keys = ("enable_ai", "anthropic_api_key", "model", "ai_provider", "ai_base_url", "ai_api_key",
                   "ai_model", "ai_timeout_seconds")
        if any(self.cfg.get(k) != fresh.get(k) for k in ai_keys):
            # вписали ключ или сменили сервис — переподключаемся без перезапуска, история сохраняется
            history = self.ai.history
            for k in ai_keys:
                self.cfg[k] = fresh.get(k)
            self.ai = make_ai(self.cfg)
            self.ai.history = history
            self.actions.ai = self.ai
            log.info("Нейросеть переподключена: %s", self.cfg.get("ai_provider"))
        self.actions.set_lists(self.cfg)
        self._apply_active_profile()
        log.info("config.json перечитан")

    # ----- кнопки -----
    # ----- микрофон -----
    def current_mic(self):
        if self.listener and self.listener.active_name:
            return self.listener.active_name
        return self.cfg.get("mic_device") or default_input_name()

    def set_mic(self, name, announce=True):
        """Сменить устройство ввода на ходу и запомнить выбор (None — как в Windows по умолчанию)."""
        self.cfg["mic_device"] = name
        save_setting("mic_device", name)
        if self.listener:
            self.listener.set_device(name)
        log.info("Выбран микрофон: %s", name or "по умолчанию")
        if announce:
            self.jobs.put(("say", line("mic_set", t=name or "микрофон Windows по умолчанию")))

    def set_mic_tuning(self, gain=None, sensitivity=None):
        """Громкость ввода и чувствительность микрофона для Капри — сразу и запоминаются."""
        if gain is not None:
            self.cfg["mic_gain"] = round(float(gain), 2)
            save_setting("mic_gain", self.cfg["mic_gain"])
            if self.listener:
                self.listener.gain = self.cfg["mic_gain"]
        if sensitivity is not None:
            self.cfg["mic_sensitivity"] = int(sensitivity)
            save_setting("mic_sensitivity", self.cfg["mic_sensitivity"])
            if self.listener:
                self.listener.sensitivity = self.cfg["mic_sensitivity"]

    def set_voice_fx(self, strength):
        """Сила цифровых эффектов голоса: 0 — чистый голос, 1.8 — как задумано, больше — сильнее."""
        self.speaker.fx = round(float(strength), 2)
        self.cfg["voice_fx"] = self.speaker.fx
        save_setting("voice_fx", self.speaker.fx)

    def set_voice_volume(self, volume):
        """Громкость голоса Капри 0..100 — только её, общая громкость Windows не меняется."""
        self.speaker.volume = int(volume)
        self.cfg["voice_volume"] = int(volume)
        save_setting("voice_volume", int(volume))
        if self.glitch_wav:
            try:
                make_glitch_sound(self.glitch_wav, self.speaker.volume)
            except Exception:
                pass

    def mic_command(self, action):
        if action == "mic_info":
            return Reply(line("mic_info", t=self.current_mic()))
        devices = [n for n, _ in input_devices()]
        if len(devices) < 2:
            return Reply(line("mic_only_one", t=self.current_mic()))
        cur = self.cfg.get("mic_device") or self.current_mic()
        idx = next((i for i, n in enumerate(devices) if n == cur or cur.startswith(n) or n.startswith(cur)), -1)
        nxt = devices[(idx + 1) % len(devices)]
        self.set_mic(nxt, announce=False)
        return Reply(line("mic_set", t=nxt))

    def call_from_click(self):
        self.last_user_interaction = time.time()
        if self.speaking:
            self.interrupt()
            return
        self.awake_until = time.time() + self.cfg["listen_window_seconds"]
        self.appear(self.cfg["listen_window_seconds"])
        self.subtitle.emit(line("listen"))

    def text_command(self, text, chat=False):
        self.summon.emit()
        self.jobs.put(("chat" if chat else "text", text))

    # ----- рабочий поток -----
    def _worker(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        while True:
            job = self.jobs.get()
            try:
                self._process(job)
            except Exception:
                log.exception("Ошибка обработки %s", job[0])
                self.say(line("crash"))

    def _process(self, job):
        kind = job[0]
        if kind == "chatter":
            text = self.chatter_line()
            if random.random() < self.cfg.get("roam_chance", 0.5):
                self.roam.emit()          # гуляет по экрану, окно с текстом сверху
                time.sleep(1.5)
            else:
                self.summon.emit()
            if not self.say(text):
                self.mode.emit("idle", 0.0)
            return
        self.last_activity = time.time()
        if kind != "say":
            self.last_user_interaction = time.time()
        if kind == "say":
            self.summon.emit()
            if len(job) > 2:
                self.anim.emit(job[2])
            if not job[1]:
                self.mode.emit("idle", 0.0)
                return
            if not self.say(job[1]):
                self.mode.emit("idle", 0.0)
            return
        if kind == "voice":
            _, cmd, audio, woke = job
            self.summon.emit()
            self.mode.emit("thinking", 0.0)
            self.subtitle.emit("> " + cmd)
            if self.cfg.get("use_google_stt"):
                better = google_stt(audio)
                if better:
                    better = better.lower()
                    if len(better) >= 2:
                        cmd = better
        else:
            cmd = job[1]
        if self.has_wake(cmd):
            # имя могло остаться в тексте («капри нажми …»), если Капри уже слушала без него
            stripped = self.strip_wake(cmd)
            if len(stripped) < 2:
                # просто позвали по имени — не болтаем, а слушаем
                self.awake_until = time.time() + self.cfg["listen_window_seconds"]
                self.mode.emit("listening", float(self.cfg["listen_window_seconds"]))
                self.subtitle.emit(line("listen"))
                return
            cmd = stripped
        log.info("Команда: %s", cmd)
        self.mode.emit("thinking", 0.0)
        self.subtitle.emit("> " + cmd)
        self.reload_config_if_changed()

        if kind == "chat":
            # Режим диалога: НИКОГДА не отправляем неизвестный текст в браузер.
            # Команды Windows доступны в отдельном режиме терминала.
            pid = self.profiles.active()["id"]
            self.history.add(pid, "user", cmd)
            role_reply = self.roles.handle(cmd)
            if role_reply:  # «давай сказку», «хватит» — включили или выключили режим
                self.chat_finished.emit(role_reply)
                self.history.add(pid, "capri", role_reply)
                if self.roles.speak() or not self.roles.role:
                    self.say(role_reply)
                self.mode.emit("idle", 0.0)
                return
            role_id = self.roles.active()
            change = self.memory.on_interaction(cmd)
            self.award(self.achv.on_message(cmd, role_id))
            self.chat_cancel = False
            self.chat_started.emit()
            remembered = self.memory.handle(cmd)
            answer = gendered(remembered) if remembered else self.chat_answer(cmd)
            if change:
                answer = answer.rstrip() + " " + change
            self.chat_finished.emit(answer)
            self.history.add(pid, "capri", answer)
            if not self.chat_cancel and self.roles.speak():
                self.say(answer)
            self.mode.emit("idle", 0.0)
            return

        role_reply = self.roles.handle(cmd)
        if role_reply:
            if kind == "text":
                self.text_reply.emit(role_reply)
            if self.roles.speak() or not self.roles.role:
                self.say(role_reply)
            self.mode.emit("idle", 0.0)
            return
        if kind == "voice" and self.roles.active():
            # включён ролевой режим: голос — это реплика в разговоре, а не команда Windows
            self.history.add(self.profiles.active()["id"], "user", cmd)
            self.award(self.achv.on_message(cmd, self.roles.role))
            self.chat_started.emit()
            answer = self.chat_answer(cmd)
            self.chat_finished.emit(answer)
            self.history.add(self.profiles.active()["id"], "capri", answer)
            if self.roles.speak():
                self.say(answer)
            self.mode.emit("idle", 0.0)
            return

        remembered = self.memory.handle(cmd)
        change = self.memory.on_interaction(cmd)
        self.award(self.achv.on_message(cmd))
        if change:
            self.jobs.put(("say", change))  # «кажется, мы подружились» — после ответа
        if remembered:
            remembered = gendered(remembered)
            if kind == "text":
                self.text_reply.emit(remembered)
            self.say(remembered)
            self.mode.emit("idle", 0.0)
            return
        reply = self.actions.handle(cmd)
        if reply is not None and reply.action in ("mic_info", "mic_next"):
            reply = self.mic_command(reply.action)
        if reply is None:
            answer, problem = None, None
            cloud = self.cfg.get("enable_ai") and self.ai.available
            # у OpenAI-совместимых сервисов нет веб-поиска: погоду и новости — в браузер, как без нейросети
            if cloud and not getattr(self.ai, "web", True) and FRESH_RE.search(cmd.lower()):
                cloud = False
            if cloud:
                answer = self.ai.ask(cmd)
                if getattr(self.ai, "failed", False):  # нет связи, ключ, баланс — пробуем локально
                    problem, answer = answer, None
            if not answer and self.local:
                answer = self.local.ask(cmd)
            if not answer:
                answer = self.lite.reply(cmd, strict=True)  # приветствия, «как дела» и т. п. без нейросети
            if not answer and problem:
                answer = problem  # пусть скажет, что с нейросетью не так, а не молча откроет поиск
            reply = Reply(answer, "answer") if answer else self.actions.fallback(cmd, force_search=bool(self.local))
        if kind == "text" and reply.text:
            self.text_reply.emit(reply.text)
        if reply.action == "answer" and self.cfg.get("teleport_on_answer"):
            self.hop.emit()  # отвечает, скача по экрану красной молнией
        if reply.action == "wave":
            self.anim.emit("capri")
        elif reply.action and reply.action.startswith("move:"):
            self.move_to.emit(reply.action[5:])
        elif reply.action == "roam":
            self.vanish.emit()
            time.sleep(0.8)
            self.roam.emit()
            time.sleep(1.5)
        if self.say(reply.text):
            return  # перебили — уже слушаем новую команду

        if reply.action == "quit":
            self.quit_app.emit()
        elif reply.action == "hide":
            self.vanish.emit()
        else:
            follow = float(self.cfg["followup_seconds"])
            self.awake_until = time.time() + follow
            self.mode.emit("listening", follow)

    def say(self, text):
        """Озвучивает текст. Возвращает True, если Капри перебили."""
        log.info("Капри: %s", text)
        self.subtitle.emit(text)
        self.mode.emit("speaking", 0.0)
        barge_in = self.cfg.get("barge_in") and self.listener
        if self.listener and not barge_in:
            self.listener.muted.set()
        self.speech_words = set(re.findall(r"\w+", text.lower().replace("ё", "е")))
        self.interrupted = False
        self.speaking = True
        try:
            self.speaker.say(text)
        finally:
            self.speaking = False
            self.speech_end = time.time()
            if barge_in and not self.interrupted:
                self.listener.reset_req.set()  # выбрасываем эхо её голоса
            if self.listener and not barge_in:
                time.sleep(0.25)
                self.listener.muted.clear()
        self._check_voice_blocked()
        return self.interrupted

    def _check_voice_blocked(self):
        """Голос Microsoft не прошёл из-за сети, а запущен zapret — один раз за сеанс объясняем
        и предлагаем добавить сервер голоса в исключения zapret."""
        err = self.speaker.edge_error
        if self.zapret_checked or not err or not zapret.NETWORK_ERROR.search(err) or not zapret.running():
            return
        self.zapret_checked = True
        all_lists = zapret.find_all_lists()
        todo = [lst for lst in all_lists if not zapret.excluded(lst)]
        if not all_lists:
            self.jobs.put(("say", line("zapret_manual")))
        elif not todo:
            self.jobs.put(("say", line("zapret_restart")))
        else:
            def fix():
                try:
                    for lst in todo:  # во все найденные копии zapret — какая из них запущена, не видно
                        zapret.add_exclude(lst)
                        log.info("Сервер голоса добавлен в исключения zapret (имя и адреса): %s", lst)
                except OSError as e:
                    log.exception("Не удалось дописать исключение zapret")
                    return Reply(line("zapret_fail", e=e))
                return Reply(line("zapret_fixed"))
            self.actions.pending = fix
            self.awake_until = time.time() + 20  # ответ «да» без имени
            self.jobs.put(("say", line("zapret_offer")))


def tray_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(255, 34, 96))
    p.setPen(QPen(QColor(150, 70, 255), 4))
    p.drawEllipse(4, 4, 56, 56)
    p.setBrush(QColor(6, 24, 20))
    p.setPen(QPen(QColor(40, 255, 150), 4))
    p.drawEllipse(14, 22, 36, 20)
    p.setBrush(QColor(40, 255, 150))
    p.drawEllipse(27, 27, 10, 10)
    p.end()
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    cfg = load_config()

    avatar = Avatar(os.path.join(BASE, "assets"))
    avatar.hide_after = float(cfg["hide_after_seconds"])
    apply_user(cfg)
    capri = Capri(cfg)
    capri.summon.connect(avatar.summon)
    capri.vanish.connect(avatar.vanish)
    capri.mode.connect(avatar.set_mode)
    capri.subtitle.connect(avatar.set_subtitle)
    capri.quit_app.connect(app.quit)
    capri.anim.connect(avatar.play_anim)
    capri.roam.connect(avatar.start_roam)
    capri.hop.connect(avatar.start_hopping)
    capri.move_to.connect(avatar.move_to_named)
    avatar.clicked.connect(capri.call_from_click)
    avatar.petted.connect(capri.on_pet)

    def ask_text():
        from terminal_dialog import TerminalDialog
        dlg = windows.get('terminal')
        if dlg is None:  # окно чата одно на всё время работы: переписка и набегающий ответ не теряются
            dlg = windows['terminal'] = TerminalDialog(capri)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    windows = {}  # открытые окна держим, пока открыты (иначе их соберёт сборщик мусора); одно окно каждого вида

    def show_window(kind, make):
        old = windows.get(kind)
        if old is not None and old.isVisible():
            old.close()
        dlg = windows[kind] = make()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_entries():
        from entries_dialog import EntriesDialog
        capri.reload_config_if_changed(speak=False)
        show_window("entries", lambda: EntriesDialog(capri.actions))

    def open_sound():
        from sound_dialog import SoundDialog
        show_window("sound", lambda: SoundDialog(capri))

    def open_profile():
        from profiles_dialog import ProfilesDialog
        show_window("profile", lambda: ProfilesDialog(capri))

    def open_settings():
        from settings_dialog import SettingsDialog
        show_window("settings", lambda: SettingsDialog(capri))

    menu = QMenu()
    for title, fn in (("Позвать Капри", capri.call_from_click),
                      ("Замолчать", capri.interrupt),
                      ("Чат и команды…", ask_text),
                      ("Мои сайты, программы и ответы…", open_entries),
                      ("Настройки Капри…", open_settings),
                      ("Профили пользователей…", open_profile),
                      ("Проверить ПК", lambda: capri.text_command("проверь компьютер")),
                      ("Спрятать", avatar.vanish),
                      ("MIC", None),
                      ("SEARCH", None),
                      ("Открыть config.json", lambda: os.startfile(CONFIG_PATH)),
                      ("Капри на GitHub (обновления)…", lambda: capri.actions.web(CAPRI_URL)),
                      (None, None),
                      ("Выход", app.quit)):
        if title is None:
            menu.addSeparator()
            continue
        if title == "MIC":
            mic_menu = menu.addMenu("Микрофон")

            def fill_mics(m=mic_menu):
                """Список устройств ввода строится при каждом открытии — чтобы видеть только что подключённые."""
                m.clear()
                chosen = capri.cfg.get("mic_device")
                options = [(None, f"По умолчанию (как в Windows: {default_input_name()})")]
                try:
                    options += [(n, n) for n, _ in input_devices()]
                except Exception:
                    log.exception("Не удалось получить список микрофонов")
                for value, label in options:
                    a = QAction(label, m)
                    a.setCheckable(True)
                    a.setChecked(value == chosen or (value is None and not chosen))
                    a.triggered.connect(lambda _=False, v=value: capri.set_mic(v))
                    m.addAction(a)
                m.addSeparator()
                tune = QAction("Громкость и чувствительность…", m)
                tune.triggered.connect(open_sound)
                m.addAction(tune)
            mic_menu.aboutToShow.connect(fill_mics)

            # «Громкость Капри» — ползунок прямо в меню, чтобы не лезть в микшер громкости Windows
            vol_menu = menu.addMenu("Громкость Капри")
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(10, 6, 10, 6)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setMinimumWidth(180)
            value = QLabel()
            value.setMinimumWidth(36)
            row.addWidget(slider)
            row.addWidget(value)
            slider.valueChanged.connect(lambda v, lbl=value: lbl.setText(f"{v}%"))
            slider.sliderReleased.connect(lambda s=slider: capri.set_voice_volume(s.value()))
            slider.valueChanged.connect(lambda v, s=slider: None if s.isSliderDown() else capri.set_voice_volume(v))
            wa = QWidgetAction(vol_menu)
            wa.setDefaultWidget(box)
            vol_menu.addAction(wa)

            def sync_volume(s=slider, lbl=value):
                s.blockSignals(True)
                s.setValue(int(capri.cfg.get("voice_volume", 100)))
                s.blockSignals(False)
                lbl.setText(f"{s.value()}%")
            vol_menu.aboutToShow.connect(sync_volume)
            continue
        if title == "SEARCH":
            # галочка: открывать ли Google, когда Капри не знает ответа (search_when_unsure)
            search_act = QAction("Искать в браузере, если не знаю", menu)
            search_act.setCheckable(True)
            search_act.toggled.connect(capri.set_search_when_unsure)
            menu.addAction(search_act)

            # галочка: появляется ли Капри сама время от времени (chatter)
            chatter_act = QAction("Появляться самой", menu)
            chatter_act.setCheckable(True)
            chatter_act.toggled.connect(capri.set_chatter)
            menu.addAction(chatter_act)

            # галочка: комментировать Spotify и YouTube (activity_comments)
            activity_act = QAction("Комментировать музыку, видео и программы", menu)
            activity_act.setCheckable(True)
            activity_act.toggled.connect(capri.set_activity)
            menu.addAction(activity_act)

            def sync_search(a=search_act, b=chatter_act, c=activity_act):
                capri.reload_config_if_changed(speak=False)  # могли поменять в config.json руками
                for act, key, default in ((a, "search_when_unsure", True), (b, "chatter", True),
                                           (c, "activity_comments", False)):
                    act.blockSignals(True)
                    act.setChecked(bool(capri.cfg.get(key, default)))
                    act.blockSignals(False)
            menu.aboutToShow.connect(sync_search)
            continue
        act = QAction(title, menu)
        act.triggered.connect(fn)
        menu.addAction(act)

    # Ctrl+Alt+C: global hotkey via Windows RegisterHotKey, no new dependencies.
    # Poll the thread message queue in Qt's main thread.
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        HOTKEY_ID = 0xCA91
        registered = bool(user32.RegisterHotKey(None, HOTKEY_ID, 0x0002 | 0x0001, ord('C')))
        if registered:
            class MSG(ctypes.Structure):
                _fields_ = [('hwnd', wintypes.HWND), ('message', wintypes.UINT),
                           ('wParam', wintypes.WPARAM), ('lParam', wintypes.LPARAM),
                           ('time', wintypes.DWORD), ('pt', wintypes.POINT)]
            hotkey_timer = QTimer(app)
            def poll_hotkey():
                msg = MSG()
                while user32.PeekMessageW(ctypes.byref(msg), None, 0x0312, 0x0312, 0x0001):
                    if msg.wParam == HOTKEY_ID:
                        ask_text()
            hotkey_timer.timeout.connect(poll_hotkey)
            hotkey_timer.start(100)
            app.aboutToQuit.connect(lambda: user32.UnregisterHotKey(None, HOTKEY_ID))
        else:
            log.warning('Ctrl+Alt+C занят другой программой; меню доступно из трея')
    except Exception:
        log.exception('Не удалось зарегистрировать горячую клавишу')

    tray = QSystemTrayIcon(tray_icon())
    tray.setToolTip("Капри — голосовой ассистент")
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: capri.call_from_click()
                           if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    avatar.menu_requested.connect(lambda pos: menu.popup(pos))

    capri.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log.exception("Капри упала при запуске")
        fatal(f"Что-то сломалось при запуске: {e}\n\nПодробности — в файле capri.log в папке Капри.")
