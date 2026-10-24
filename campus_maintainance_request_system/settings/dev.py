import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.is_file():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name.strip(), value)

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only-key")
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

if os.environ.get("DB_ENGINE", "sqlite").lower() == "sqlite":
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        }
    }
