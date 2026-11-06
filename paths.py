"""Где лежат файлы Капри — одинаково при запуске из исходников (run.bat) и из собранного Capri.exe.

APP_DIR — папка для данных пользователя (config.json, profiles.json, history/, models/, capri.log, reports/):
          рядом с main.py или рядом с Capri.exe.
RES_DIR — папка с ресурсами программы (assets/, bundled/): рядом с main.py или внутри сборки PyInstaller.
"""
import os
import sys
import zipfile

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = APP_DIR

EXE_NAME = os.path.splitext(os.path.basename(sys.executable))[0].lower() if FROZEN else ""

MODEL_NAME = "vosk-model-small-ru-0.22"


def app(*parts):
    return os.path.join(APP_DIR, *parts)


def res(*parts):
    """Ресурс программы; если рядом с exe лежит своя копия (например, свои позы в assets), берётся она."""
    own = os.path.join(APP_DIR, *parts)
    return own if FROZEN and os.path.exists(own) else os.path.join(RES_DIR, *parts)


def model_ready(path):
    return os.path.isfile(os.path.join(path, "am", "final.mdl"))


def ensure_model(model_path, log=None):
    """Модели распознавания речи нет, а архив с ней есть (bundled/) — распаковываем.
    Так Капри заводится и без setup.bat, и в собранном exe. Возвращает True, если модель на месте."""
    if model_ready(model_path):
        return True
    archive = res("bundled", MODEL_NAME + ".zip")
    if not os.path.isfile(archive):
        return False
    target_root = os.path.dirname(model_path)
    try:
        os.makedirs(target_root, exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():  # защита от путей вида ../ внутри архива
                dest = os.path.realpath(os.path.join(target_root, name))
                if not dest.startswith(os.path.realpath(target_root) + os.sep):
                    raise zipfile.BadZipFile("подозрительный путь в архиве: " + name)
            z.extractall(target_root)
        if log:
            log.info("Модель распознавания речи распакована в %s", target_root)
    except (OSError, zipfile.BadZipFile) as e:
        if log:
            log.error("Не удалось распаковать модель: %s", e)
        return False
    return model_ready(model_path)
