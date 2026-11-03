"""История текстового чата с Капри: у каждого профиля свой файл history/<id профиля>.jsonl.

Окно чата показывает последние сообщения после перезапуска, а нейросеть получает последние реплики
как контекст, чтобы разговор продолжался, а не начинался заново."""
import json
import os
import threading
import time

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")
KEEP = 2000  # столько сообщений храним в файле, старые обрезаются


class ChatHistory:
    def __init__(self):
        self.lock = threading.Lock()

    @staticmethod
    def path(profile_id):
        safe = "".join(ch for ch in str(profile_id) if ch.isalnum() or ch in "-_") or "default"
        return os.path.join(DIR, safe + ".jsonl")

    def add(self, profile_id, role, text):
        """role: user | capri | note"""
        if not text:
            return
        rec = {"role": role, "text": text, "ts": int(time.time())}
        with self.lock:
            os.makedirs(DIR, exist_ok=True)
            with open(self.path(profile_id), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._trim(profile_id)

    def load(self, profile_id, limit=200):
        try:
            with open(self.path(profile_id), encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        out = []
        for raw in lines[-limit:]:
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out

    def context(self, profile_id, pairs=6):
        """Последние реплики в формате нейросети (user/assistant) — для продолжения разговора."""
        msgs = [{"role": "user" if r["role"] == "user" else "assistant", "content": r["text"]}
                for r in self.load(profile_id, pairs * 2 + 4) if r["role"] in ("user", "capri")]
        msgs = msgs[-pairs * 2:]
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        return msgs

    def clear(self, profile_id):
        with self.lock:
            try:
                os.remove(self.path(profile_id))
            except OSError:
                pass

    def _trim(self, profile_id):
        p = self.path(profile_id)
        try:
            if os.path.getsize(p) < 600_000:
                return
            with open(p, encoding="utf-8") as f:
                lines = f.readlines()
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                f.writelines(lines[-KEEP:])
            os.replace(p + ".tmp", p)
        except OSError:
            pass
