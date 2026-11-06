"""Капри комментирует, что делает пользователь: открыл Spotify, слушает трек, смотрит YouTube.

Как это работает:
  - раз в несколько секунд читается список медиа-сессий Windows (как у плашки громкости): оттуда берётся
    название трека или видео; плюс проверяется, запущен ли Spotify и какое окно сейчас на переднем плане;
  - новое событие должно продержаться два опроса подряд (чтобы не реагировать на промежуточные заголовки);
  - реплики ограничены паузой (activity_cooldown_minutes), шансом (activity_music_chance) и не звучат,
    пока Капри говорит, слушает команду или на экране игра/видео во весь экран;
  - текст реплики пишет локальная нейросеть (если запущена), иначе берётся готовая фраза из persona.LINES.
    В облако (Claude) названия уходят только при activity_use_cloud: true.
Включается галочкой в трее или activity_comments в config.json (по умолчанию выключено).
"""
import asyncio
import ctypes
import logging
import random
import re
import threading
import time

from persona import line

log = logging.getLogger("capri")

POLL = 3.0
MUSIC_APPS = ("spotify", "music", "музык", "vlc", "foobar", "aimp", "winamp", "itunes", "tidal", "deezer", "zvuk")
BROWSERS = ("chrome", "msedge", "edge", "firefox", "opera", "brave", "vivaldi", "yandex", "browser")
ADS = ("advertisement", "реклама", "spotify", "")
YT_TITLE = re.compile(r"^(?:\(\d+\)\s*)?(.+?)\s+[-–—]\s+YouTube\b", re.IGNORECASE)


class Event:
    def __init__(self, kind, detail, force, created):
        self.kind = kind            # "open" | "music" | "yt"
        self.detail = detail
        self.force = force          # начало занятия (не смена трека): реплика почти всегда
        self.created = created
        self.expires = created + (120 if force else 60)


def _foreground_title():
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return ""
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def _spotify_running():
    try:
        import psutil
        return any((p.info.get("name") or "").lower() == "spotify.exe"
                   for p in psutil.process_iter(["name"]))
    except Exception:
        return False


def _media_sessions():
    """[(источник, название, исполнитель, играет)] по всем медиа-сессиям Windows."""
    import media

    async def go():
        _, sessions = await media._sessions()
        out = []
        for s in sessions:
            p = await s.try_get_media_properties_async()
            out.append(((s.source_app_user_model_id or "").lower(), (p.title or "").strip(),
                        (p.artist or "").strip(), s.get_playback_info().playback_status == media.PLAYING))
        return out
    return asyncio.run(go())


def _clean(text):
    from local_ai import FOREIGN, SEARCH_MARK, drop_third_person
    text = drop_third_person(re.sub(r"\s+", " ", FOREIGN.sub("", text or "")).strip().strip('"«»'))
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text).strip()
    if SEARCH_MARK in text.upper()[:20]:
        return None
    return text if 5 < len(text) < 200 and re.search(r"[.!?…]$", text) else None


class ActivityWatcher:
    def __init__(self, capri, fullscreen=None):
        self.capri = capri
        self.fullscreen = fullscreen or (lambda: False)
        self.prev_proc = None
        self.commented = {}      # kind -> ключ, о котором уже сказали (или решили не говорить)
        self.stable = {}         # kind -> [ключ, сколько опросов подряд]
        self.pending = None
        self.last_comment = 0.0
        self.baseline = True

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="activity").start()

    # ----- настройки -----
    def _cfg(self, key, default):
        return self.capri.cfg.get(key, default)

    def enabled(self):
        return bool(self._cfg("activity_comments", False))

    # ----- опрос -----
    def _snapshot(self):
        music = yt = None
        try:
            sessions = _media_sessions()
        except Exception:
            sessions = []
        title = _foreground_title()
        m = YT_TITLE.match(title)
        for src, t, artist, playing in sessions:
            if not playing or not t:
                continue
            music_like = any(k in src for k in ("music", "музык", "spotify"))
            is_browser = any(b in src for b in BROWSERS) and not music_like
            is_music = not is_browser and any(a in src for a in MUSIC_APPS)
            if is_music:
                if music is None and t.lower() not in ADS:
                    music = f"{artist} — {t}" if artist else t
            elif yt is None and m:
                # на переднем плане YouTube, и что-то играет не из плеера музыки (у Firefox id вместо имени)
                yt = t if len(t) > 3 else m.group(1)
        return {"proc": _spotify_running(), "music": music, "yt": yt}

    def _events(self, snap):
        now = time.time()
        out = []
        if self.baseline:
            # первый опрос после включения: запоминаем, что уже играет, и об этом молчим
            self.prev_proc = snap["proc"]
            for kind in ("music", "yt"):
                if snap[kind]:
                    self.commented[kind] = snap[kind]
            self.baseline = False
            return out
        if snap["proc"] and not self.prev_proc:
            out.append(Event("open", "Spotify", True, now))
        self.prev_proc = snap["proc"]
        for kind in ("music", "yt"):
            key = snap[kind]
            if key is None:
                self.commented.pop(kind, None)
                self.stable.pop(kind, None)
                continue
            if key == self.commented.get(kind):
                self.stable.pop(kind, None)
                continue
            s = self.stable.get(kind)
            if s and s[0] == key:
                s[1] += 1
            else:
                self.stable[kind] = s = [key, 1]
            if s[1] < 2:
                continue
            start = kind not in self.commented  # занятие началось только что, а не сменился трек
            self.commented[kind] = key
            self.stable.pop(kind, None)
            chance = 1.0 if start else float(self._cfg("activity_music_chance", 0.35))
            if kind == "yt":
                chance = 0.8 if start else 0.3
            if random.random() <= chance:
                out.append(Event(kind, key, start, now))
        return out

    # ----- можно ли сейчас говорить -----
    def _quiet(self):
        c = self.capri
        now = time.time()
        return (not c.speaking and c.jobs.empty() and now > c.awake_until
                and now - c.last_activity > 8 and not self.fullscreen()
                and not c.in_quiet_hours())  # тихие часы из «Настроек Капри»

    def _gap_ok(self, ev):
        factor = self.capri.cooldown_factor() if hasattr(self.capri, "cooldown_factor") else 1.0
        gap = 45 if ev.force else float(self._cfg("activity_cooldown_minutes", 8)) * 60 * factor
        return time.time() - self.last_comment >= gap

    # ----- текст реплики -----
    def _prompt(self, ev):
        tail = (" Скажи одну короткую живую реплику, до восемнадцати слов, в своём характере. "
                "Не выдумывай факты о песне или видео, если не уверена. Не спрашивай, чем помочь.")
        if ev.kind == "open":
            return "Пользователь только что открыл Spotify." + tail
        if ev.kind == "music":
            return f"Пользователь слушает музыку: «{ev.detail}»." + tail
        return f"Пользователь смотрит на YouTube видео «{ev.detail}»." + tail

    def _fallback(self, ev):
        short = ev.detail if len(ev.detail) <= 60 else ev.detail[:57].rstrip() + "…"
        key = {"open": "act_open", "music": "act_music", "yt": "act_yt"}[ev.kind]
        return line(key, t=short)

    def _generate(self, ev):
        c = self.capri
        prompt = self._prompt(ev)
        if self._cfg("activity_use_cloud", False) and self._cfg("enable_ai", False) and c.ai.available:
            try:
                from ai import SYSTEM
                from persona import user_context
                text = _clean(c.ai._call(SYSTEM + "\n" + user_context(),
                                         [{"role": "user", "content": prompt}], []))
                if text:
                    return text
            except Exception:
                log.exception("Комментарий через облако не получился")
        if c.local and c.local.running():
            text = _clean(c.local.comment(prompt))
            if text:
                return text
        return self._fallback(ev)

    # ----- цикл -----
    def _loop(self):
        was_enabled = False
        while True:
            time.sleep(POLL)
            try:
                if not self.enabled():
                    if was_enabled:  # выключили: при включении заново не комментируем то, что уже играет
                        self.baseline = True
                        self.commented.clear()
                        self.stable.clear()
                        self.pending = None
                        was_enabled = False
                    continue
                was_enabled = True
                for ev in self._events(self._snapshot()):
                    if self.pending is None or ev.force or not self.pending.force:
                        self.pending = ev
                ev = self.pending
                if not ev:
                    continue
                if time.time() > ev.expires:
                    self.pending = None
                    continue
                if not (self._quiet() and self._gap_ok(ev)):
                    continue
                self.pending = None
                text = self._generate(ev)
                if not self._quiet() or not self.enabled():
                    continue  # пока думала, началось что-то другое — не перебиваем
                self.last_comment = time.time()
                log.info("Комментарий (%s): %s", ev.kind, text)
                self.capri.jobs.put(("say", text))
            except Exception:
                log.exception("Сбой наблюдателя за занятиями")
                time.sleep(10)
