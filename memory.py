"""Память Капри о пользователе и шкала отношений. Всё хранится в профиле (profiles.json), у каждого своё.

Память:   «запомни, что я люблю рок», «забудь, что я люблю рок», «забудь всё обо мне»,
          «что ты обо мне знаешь», «мой день рождения 5 марта» (или «запомни, что мой день рождения…»).
          Факты попадают в промпт нейросети (разговор, реплики, комментарии к музыке) и в готовые фразы.
Отношения: число 0–100 (старт 50). Растёт от общения, «спасибо», похвалы, поглаживания; падает от грубости,
          от игнора (серия «требует внимания» ушла в пустоту) и за дни без общения. Видно в окне профиля.
"""
import datetime
import logging
import random
import re
import threading
import time

from persona import gendered

log = logging.getLogger("capri")

MAX_FACTS = 50
MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
          "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
MONTH_NAMES = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
               "октября", "ноября", "декабря"]

REMEMBER = re.compile(r"^(?:капри\s*,?\s*)?(?:запомни|запиши|не забудь)\s*[,:]?\s*(?:пожалуйста\s*,?\s*)?"
                      r"(?:что\s+|про меня\s*[,:]?\s*|обо мне\s*[,:]?\s*)?(?P<fact>(?:я|мне|меня|мой|моя|моё|мое|мои|мою|моего|моей|моих|у меня)\b.+)$",
                      re.IGNORECASE)
REMEMBER_THAT = re.compile(r"^(?:капри\s*,?\s*)?(?:запомни|запиши|не забудь)\s*[,:]?\s*что\s+(?P<fact>.+)$", re.IGNORECASE)
FORGET_ALL = re.compile(r"^(?:капри\s*,?\s*)?забудь (?:вс[её]|всё что знаешь|всё что помнишь) (?:обо мне|про меня)$",
                        re.IGNORECASE)
FORGET = re.compile(r"^(?:капри\s*,?\s*)?забудь\s*[,:]?\s*(?:что\s+|про\s+|о том,? что\s+)(?P<fact>.+)$", re.IGNORECASE)
RECALL = re.compile(r"(что|чего) ты (обо мне|про меня) (знаешь|помнишь|запомнила)|"
                    r"что ты (знаешь|помнишь) (обо мне|про меня)|что ты запомнила|"
                    r"какие у тебя (факты|заметки) (обо мне|про меня)", re.IGNORECASE)
BIRTHDAY = re.compile(r"(?:мой|у меня) день рождени[яе]\s*(?:—|-|:)?\s*(?P<d>\d{1,2})[\s./-]*(?P<m>[а-яё]+|\d{1,2})",
                      re.IGNORECASE)
BIRTHDAY_ASK = re.compile(r"когда (у меня|мой) день рождени", re.IGNORECASE)

# первое лицо → второе: так факт читается и в промпте, и в ответе («Запомнила: ты любишь рок»)
SWAP = [(r"\bя\b", "ты"), (r"\bмне\b", "тебе"), (r"\bменя\b", "тебя"), (r"\bмной\b", "тобой"),
        (r"\bмой\b", "твой"), (r"\bмоя\b", "твоя"), (r"\bмо[её]\b", "твоё"), (r"\bмои\b", "твои"),
        (r"\bмоего\b", "твоего"), (r"\bмоей\b", "твоей"), (r"\bмоих\b", "твоих"), (r"\bмоему\b", "твоему"),
        (r"\bмою\b", "твою"), (r"\bсебя\b", "себя")]


def clean_fact(text):
    """Факт словами пользователя: «я люблю рок» (без «что», точки в конце и лишних пробелов)."""
    t = re.sub(r"\s+", " ", text).strip().rstrip(".!")
    t = re.sub(r"^(что|то что)\s+", "", t, flags=re.IGNORECASE)
    return t[:1].lower() + t[1:] if t[:2].lower() in ("я ", "мн", "ме", "мо", "у ") else t


def to_second_person(text):
    out = text.strip().rstrip(".!")
    for a, b in SWAP:
        out = re.sub(a, b, out, flags=re.IGNORECASE)
    return out


def _norm(text):
    return re.sub(r"[^\wё ]", "", text.lower().replace("ё", "е")).strip()


def parse_birthday(day, month):
    try:
        d = int(day)
        m = int(month) if month.isdigit() else next(
            (n for stem, n in sorted(MONTHS.items(), key=lambda x: -len(x[0])) if month.lower().startswith(stem)), 0)
        datetime.date(2000, m, d)  # проверка: 31 февраля не бывает
        return f"{d:02d}.{m:02d}"
    except (ValueError, StopIteration):
        return None


def birthday_words(value):
    d, m = value.split(".")
    return f"{int(d)} {MONTH_NAMES[int(m) - 1]}"


# ---------- отношения ----------
LEVELS = [(0, "hurt", "Обижена"), (25, "cool", "Прохладно"), (45, "neutral", "Нейтрально"),
          (60, "friends", "Дружба"), (80, "close", "Близкие")]
MOOD_PROMPT = {
    "hurt": "Ты обижена на пользователя: он долго тебя игнорировал или грубил. Отвечай холоднее, с лёгким упрёком, "
            "но не грубо; оттаиваешь, когда он проявляет внимание.",
    "cool": "Отношения с пользователем пока прохладные: держишься сдержанно.",
    "neutral": "",
    "friends": "Вы с пользователем дружите: тепло, с шутками, как с хорошим другом.",
    "close": "Вы с пользователем очень близки: говоришь тепло и с нежностью, радуешься ему, но остаёшься собой.",
}
LEVEL_LINES = {
    "up": {"friends": ["Знаешь, мне с тобой хорошо. Кажется, мы подружились.",
                       "Мы с тобой уже почти друзья. Мне нравится."],
           "close": ["Ты для меня уже не просто пользователь. Ты мой человек.",
                     "Кажется, я к тебе привязалась. Не смейся."],
           "neutral": ["Ладно, я больше не дуюсь. Почти."],
           "cool": ["Ну хоть так. Обида понемногу проходит."]},
    "down": {"hurt": ["Всё. Я обиделась. Серьёзно.", "Мне неприятно, что ты меня не замечаешь."],
             "cool": ["Что-то ты совсем про меня [забыл|забыла]. Мне это не нравится.",
                      "Мы как-то отдалились. Грустно."],
             "neutral": ["Мне не хватает наших разговоров."],
             "friends": ["Ты в последнее время редко со мной болтаешь."]},
}
INSULT_DOWN = ["Ты сегодня какой-то [грубый|грубая]. Мне неприятно.",
               "Знаешь, после таких слов мне с тобой уже не так тепло.",
               "Я запомню, как ты со мной разговариваешь."]
GAINS = {"talk": 1, "thanks": 2, "praise": 3, "pet": 1, "greet": 1}
LOSSES = {"insult": -6, "ignored": -3, "absent_day": -2}


def level_of(score):
    key, name = "neutral", "Нейтрально"
    for floor, k, n in LEVELS:
        if score >= floor:
            key, name = k, n
    return key, name


class Memory:
    def __init__(self, capri):
        self.capri = capri
        self.lock = threading.Lock()

    # ----- хранение в активном профиле -----
    @property
    def profile(self):
        return self.capri.profiles.active()

    def facts(self):
        return self.profile.setdefault("memory", [])

    def bond(self):
        b = self.profile.setdefault("bond", {})
        b.setdefault("score", 50)
        b.setdefault("last_seen", time.time())
        b.setdefault("day", "")
        b.setdefault("day_gain", 0)
        return b

    def save(self):
        self.capri.profiles.save()
        self.push_context()

    def push_context(self):
        """Факты, день рождения и настроение — в промпт нейросети (persona.set_memory)."""
        from persona import set_memory
        facts = ["«" + f["text"] + "»" for f in self.facts()]
        bd = self.profile.get("birthday")
        if bd:
            facts.append("день рождения " + birthday_words(bd))
        set_memory(facts, MOOD_PROMPT[level_of(self.bond()["score"])[0]])

    # ----- команды -----
    def handle(self, text):
        """Ответ, если это команда памяти, иначе None."""
        t = text.strip()
        low = t.lower().replace("ё", "е")
        m = BIRTHDAY.search(t)
        if m and re.search(r"(мой|у меня) день рождени", low) and not BIRTHDAY_ASK.search(t):
            value = parse_birthday(m.group("d"), m.group("m"))
            if not value:
                return "Такой даты не бывает. Скажи, например: «мой день рождения 5 марта»."
            with self.lock:
                self.profile["birthday"] = value
                self.save()
            return f"Запомнила: день рождения {birthday_words(value)}. Готовься к поздравлениям."
        if BIRTHDAY_ASK.search(t):
            bd = self.profile.get("birthday")
            return (f"Твой день рождения {birthday_words(bd)}. Я помню." if bd
                    else "Ты мне не [говорил|говорила]. Скажи: «мой день рождения 5 марта».")
        if FORGET_ALL.match(low):
            with self.lock:
                self.facts().clear()
                self.profile.pop("birthday", None)
                self.save()
            return "Всё стёрла. Будем знакомиться заново."
        m = FORGET.match(t)
        if m and not re.match(r"^(забудь|удали|убери) (свой |мой |этот )?ответ", low):
            return self.forget(m.group("fact"))
        if RECALL.search(low):
            return self.recall()
        m = REMEMBER.match(t) or REMEMBER_THAT.match(t)
        if m:
            return self.remember(m.group("fact"))
        return None

    def remember(self, raw):
        fact = clean_fact(raw)
        if len(_norm(fact)) < 3:
            return "А что именно запомнить?"
        with self.lock:
            facts = self.facts()
            key = _norm(fact)
            if any(_norm(f["text"]) == key for f in facts):
                return "Это я уже знаю."
            facts.append({"text": fact, "ts": int(time.time())})
            del facts[:-MAX_FACTS]
            self.save()
        log.info("Запомнила: %s", fact)
        if hasattr(self.capri, "achv"):
            self.capri.award(self.capri.achv.on_event("fact"))
        return gendered(random.choice(["Запомнила.", "Записала себе. Буду знать.", "Поняла, запомнила.",
                                       "Ага, теперь я это знаю."]))

    def forget(self, raw):
        words = [w for w in _norm(clean_fact(raw)).split() if len(w) > 2]
        if not words:
            return "Что именно забыть?"
        with self.lock:
            facts = self.facts()
            keep = [f for f in facts if sum(w in _norm(f["text"]) for w in words) < max(1, len(words) * 0.6)]
            removed = len(facts) - len(keep)
            facts[:] = keep
            if removed:
                self.save()
        return "Забыла." if removed else "Я такого о тебе и не помню."

    def recall(self):
        facts = ["«" + f["text"] + "»" for f in self.facts()]
        bd = self.profile.get("birthday")
        tail = f" А день рождения у тебя {birthday_words(bd)}." if bd else ""
        if not facts:
            if bd:
                return tail.strip()
            return "Пока ничего. Скажи: «запомни, что я люблю рок» — и я буду помнить."
        if len(facts) > 6:
            return ("Много чего. Например, ты [говорил|говорила]: " + ", ".join(random.sample(facts, 6)) +
                    ". Полный список в окне профиля." + tail)
        return "Ты мне [говорил|говорила]: " + ", ".join(facts) + "." + tail

    def random_fact(self):
        facts = self.facts()
        return random.choice(facts)["text"] if facts else None

    # ----- отношения -----
    def score(self):
        return self.bond()["score"]

    def level(self):
        return level_of(self.score())

    def _change(self, delta, reason):
        """Меняет счёт. Возвращает реплику, если сменился уровень отношений, иначе None."""
        with self.lock:
            b = self.bond()
            today = datetime.date.today().isoformat()
            if b["day"] != today:
                b["day"], b["day_gain"] = today, 0
            if delta > 0:
                if b["day_gain"] >= 15:  # в день отношения растут не больше чем на 15
                    return None
                delta = min(delta, 15 - b["day_gain"])
                b["day_gain"] += delta
            before = level_of(b["score"])[0]
            b["score"] = max(0, min(100, b["score"] + delta))
            after = level_of(b["score"])[0]
            self.save()
        log.info("Отношения %+d (%s): %d", delta, reason, b["score"])
        if after != before:
            way = "up" if delta > 0 else "down"
            if reason == "грубость":
                return gendered(random.choice(INSULT_DOWN))
            variants = LEVEL_LINES[way].get(after)
            if variants:
                return gendered(random.choice(variants))
        return None

    def on_interaction(self, text=""):
        """Пользователь обратился к Капри. Возвращает реплику смены уровня (или None)."""
        now = time.time()
        b = self.bond()
        last = b.get("last_talk", 0)
        b["last_seen"] = now
        low = (text or "").lower()
        if re.search(r"\b(дура|тупая|идиотк|дебил|заткнись|бесишь|ненавижу тебя|отвали)", low):
            return self._change(LOSSES["insult"], "грубость")
        if re.search(r"спасиб|благодар|\bспс\b", low):
            return self._change(GAINS["thanks"], "спасибо")
        if re.search(r"ты (молодец|умница|классная|крутая|лучшая|супер|хорошая|красивая|милая)|люблю тебя", low):
            return self._change(GAINS["praise"], "похвала")
        if now - last < 120:  # за болтовню — не чаще раза в две минуты
            return None
        b["last_talk"] = now
        return self._change(GAINS["talk"], "общение")

    def on_pet(self):
        return self._change(GAINS["pet"], "поглаживание")

    def on_ignored(self):
        return self._change(LOSSES["ignored"], "игнор")

    def apply_absence(self):
        """При запуске: за каждый день без общения (после первого) отношения немного остывают."""
        b = self.bond()
        days = int((time.time() - b.get("last_seen", time.time())) // 86400)
        if days >= 2:
            self._change(LOSSES["absent_day"] * min(days - 1, 10), f"не общались {days} дн.")
        return days


HURT_CHATTER = ["Я всё ещё обижена, если что.", "Могла бы и поговорить со мной, между прочим.",
                "Ладно, я тут. Сижу. Одна. Как всегда.", "Не думай, что я забыла, как ты меня [игнорировал|игнорировала]."]
FACT_CHATTER = ["Помню, ты [говорил|говорила]: «{f}». Видишь, я внимательная.",
                "А я помню твоё «{f}». Я всё запоминаю.",
                "Вспомнила твои слова: «{f}». Мне это в тебе нравится."]


def hurt_line():
    return gendered(random.choice(HURT_CHATTER))


def fact_line(fact):
    return gendered(random.choice(FACT_CHATTER).format(f=fact))
