"""Ответы на вопросы через облачную нейросеть.

Два вида подключения (поле ai_provider в config.json):
  "anthropic"          — Claude напрямую по ключу Anthropic (с веб-поиском для свежих фактов);
  "openai_compatible"  — любой сервис с API в формате OpenAI: OrcaRouter, OpenRouter, DeepSeek и т. п.
                         Нужны ai_base_url, ai_api_key и ai_model. Работает на встроенном urllib,
                         ничего докачивать не нужно; ответ приходит потоком (стриминг).
"""
import datetime
import json
import logging
import os
import re
import urllib.error
import urllib.request

from persona import FRESH, CHARACTER, SPEECH_RULES, user_context

log = logging.getLogger("capri")

SYSTEM = f"""{CHARACTER}

{SPEECH_RULES}
Для свежих фактов (погода, новости, курсы, расписания) используй веб-поиск.
Командами ПК (открыть сайт/приложение, громкость, яркость, диагностика) занимается отдельный модуль;
если просят то, чего ты сделать не можешь, скажи, какую команду произнести, например «Капри, открой ютуб»."""


class AI:
    def __init__(self, cfg):
        self.model = cfg.get("model", "claude-opus-5-5")
        self.history = []
        self.failed = False  # последний ask() вернул текст ошибки, а не ответ
        self.web = True      # у Claude есть веб-поиск
        self.client = None
        key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if key:
            import anthropic
            self.client = anthropic.Anthropic(api_key=key, timeout=60, max_retries=2)

    @property
    def available(self):
        return self.client is not None

    def _call(self, system, messages, tools):
        """Запрос с серверным фолбэком при отказе и продолжением при pause_turn."""
        msgs = list(messages)
        extra = {"tools": tools} if tools else {}
        for _ in range(4):
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                messages=msgs,
                **extra,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
            if resp.stop_reason == "pause_turn":
                msgs.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason == "refusal":
                return "На это я ответить не могу."
            text = " ".join(b.text for b in resp.content if b.type == "text").strip()
            return text or "Хм, пустой ответ. Спроси ещё раз."
        return "Поиск затянулся, попробуй переформулировать."

    def ask(self, question, on_delta=None):
        """on_delta(текст) — для совместимости с потоковым режимом: Claude отдаёт ответ целиком."""
        if not self.available:
            return ("Чтобы я отвечала на вопросы, впиши ключ Anthropic API в config.json, "
                    "в поле anthropic_api_key.")
        import anthropic
        self.failed = True  # сбросим, если ответ получен
        now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        self.history.append({"role": "user", "content": f"[{now}] {question}"})
        self.history = self.history[-12:]
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)
        try:
            answer = self._call(SYSTEM + "\n" + user_context(), self.history,
                                [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}])
        except anthropic.AuthenticationError:
            self.history.pop()
            return "Ключ API не подходит. Проверь anthropic_api_key в config.json."
        except anthropic.RateLimitError:
            self.history.pop()
            return "Слишком много запросов, подожди немного."
        except anthropic.APIConnectionError:
            self.history.pop()
            return "Нет связи с сервером. Проверь интернет."
        except anthropic.APIStatusError as e:
            self.history.pop()
            log.error("API error %s: %s", e.status_code, e.message)
            return "Сервер вернул ошибку, попробуй позже."
        self.failed = False
        if on_delta:
            on_delta(answer)
        self.history.append({"role": "assistant", "content": answer})
        return answer

    def summarize_report(self, report):
        if not self.available:
            return None
        try:
            return self._call(
                SYSTEM + "\n" + user_context(),
                [{"role": "user", "content":
                  "Вот отчёт диагностики моего ПК. Скажи голосом 2–4 предложения: общее состояние, "
                  "главные проблемы и что конкретно сделать. Ошибки, которые обычно безвредны "
                  "(например, DistributedCOM), не раздувай.\n\n" + report[:30000]}],
                [],
            )
        except Exception:
            log.exception("summarize_report")
            return None


# ---------- OpenAI-совместимые сервисы (OrcaRouter и другие) ----------

COMPAT_SYSTEM = f"""{CHARACTER}

{SPEECH_RULES}
У тебя нет доступа к интернету. Если спрашивают о свежих событиях (погода, новости, курсы, цены),
честно скажи, что не знаешь свежих данных, и предложи сказать «Капри, найди …».
Командами ПК (открыть сайт/приложение, громкость, яркость, диагностика) занимается отдельный модуль;
если просят то, чего ты сделать не можешь, скажи, какую команду произнести, например «Капри, открой ютуб»."""


class CompatError(Exception):
    """Понятная пользователю ошибка подключения (её текст Капри говорит вслух)."""


class OpenAICompatAI:
    """Чат через API в формате OpenAI (/chat/completions). Тот же интерфейс, что у AI."""

    def __init__(self, cfg):
        provider = str(cfg.get("ai_provider", "")).lower()
        base = (cfg.get("ai_base_url") or "").strip()
        model = (cfg.get("ai_model") or "").strip()
        if provider == "openrouter":
            # OpenRouter: адрес и модель по умолчанию свои (значения OrcaRouter из старого config не мешают)
            if not base or "orcarouter" in base:
                base = "https://openrouter.ai/api/v1"
            if not model or model.startswith("orcarouter/"):
                model = "openrouter/auto"
        self.base_url = (base or "https://api.orcarouter.ai/v1").rstrip("/")
        self.model = model or "orcarouter/auto"
        self.openrouter = "openrouter.ai" in self.base_url
        self.key = (cfg.get("ai_api_key") or os.environ.get("OPENROUTER_API_KEY" if self.openrouter else
                                                             "ORCAROUTER_API_KEY")
                    or os.environ.get("OPENAI_API_KEY") or "").strip()
        self.timeout = float(cfg.get("ai_timeout_seconds", 60))
        self.history = []
        self.failed = False
        self.web = False  # веб-поиска нет: свежие факты ищет браузер

    @property
    def available(self):
        return bool(self.key)

    # ----- HTTP -----
    def _request(self, messages, max_tokens, stream):
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": 0.7, "stream": stream}
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.key,
                   "Accept": "text/event-stream" if stream else "application/json", "User-Agent": "Capri/1.0"}
        if self.openrouter:  # подпись приложения в статистике OpenRouter (необязательно)
            headers["X-Title"] = "Capri"
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            log.error("%s вернул %s: %s", self.base_url, e.code, detail)
            if e.code in (401, 403):
                raise CompatError("Ключ не подходит. Проверь ai_api_key в config.json.")
            if e.code == 402:
                raise CompatError("На счёте сервиса нейросети закончились деньги. Пополни баланс.")
            if e.code == 404:
                raise CompatError("Сервис не знает модель " + self.model + ". Проверь ai_model в config.json.")
            if e.code == 429:
                raise CompatError("Слишком много запросов, подожди немного.")
            raise CompatError("Сервер нейросети вернул ошибку, попробуй позже.")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.error("Нет связи с %s: %s", self.base_url, e)
            raise CompatError("Нет связи с сервером нейросети. Проверь интернет.")

    def _complete(self, messages, max_tokens=800, on_delta=None):
        """Текст ответа. С on_delta ответ читается потоком и кусочки отдаются по мере прихода."""
        if on_delta is None:
            with self._request(messages, max_tokens, False) as r:
                data = json.loads(r.read().decode("utf-8"))
            return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        parts = []
        with self._request(messages, max_tokens, True) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                if delta:
                    parts.append(delta)
                    if on_delta(delta) is False:  # «Остановить» в окне чата
                        break
        return "".join(parts)

    @staticmethod
    def _clean(text):
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
        return re.sub(r"\s+", " ", text).strip()

    # ----- интерфейс как у AI -----
    def _call(self, system, messages, tools):
        """Совместимость с AI._call (activity.py просит короткие реплики). tools игнорируются."""
        msgs = [{"role": "system", "content": system.replace(SYSTEM, COMPAT_SYSTEM)}] + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else str(m["content"])}
            for m in messages]
        return self._clean(self._complete(msgs, 300))

    def ask(self, question, on_delta=None):
        self.failed = True
        if not self.available:
            return "Чтобы я отвечала через нейросеть, впиши ключ в config.json, в поле ai_api_key."
        now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        self.history.append({"role": "user", "content": question})
        self.history = self.history[-12:]
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)
        system = COMPAT_SYSTEM + "\n" + user_context() + f"\nСейчас {now}."
        try:
            answer = self._clean(self._complete([{"role": "system", "content": system}] + self.history,
                                                on_delta=on_delta))
        except CompatError as e:
            self.history.pop()
            return str(e)
        except Exception:
            log.exception("Сбой OpenAI-совместимого сервиса")
            self.history.pop()
            return "Что-то пошло не так с нейросетью, попробуй ещё раз."
        if not answer:
            self.history.pop()
            return "Хм, пустой ответ. Спроси ещё раз."
        self.failed = False
        self.history.append({"role": "assistant", "content": answer})
        return answer

    def summarize_report(self, report):
        if not self.available:
            return None
        try:
            return self._clean(self._complete([
                {"role": "system", "content": COMPAT_SYSTEM + "\n" + user_context()},
                {"role": "user", "content":
                 "Вот отчёт диагностики моего ПК. Скажи голосом 2–4 предложения: общее состояние, "
                 "главные проблемы и что конкретно сделать. Безвредные ошибки вроде DistributedCOM "
                 "не раздувай.\n\n" + report[:30000]}], 500)) or None
        except Exception:
            log.exception("summarize_report")
            return None


def make_ai(cfg):
    """Облачная нейросеть по полю ai_provider: anthropic (по умолчанию) или openai_compatible."""
    if str(cfg.get("ai_provider", "anthropic")).lower() in ("openai_compatible", "openai", "orcarouter", "openrouter"):
        return OpenAICompatAI(cfg)
    return AI(cfg)
