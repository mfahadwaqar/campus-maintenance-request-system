import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

REPAIR_CLOSE_DAYS = 15

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "reports.apps.ReportsConfig",
    "assignments.apps.AssignmentsConfig",
    "notifications.apps.NotificationsConfig",
    "ps4.apps.Ps4Config",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "campus_maintainance_request_system.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
WSGI_APPLICATION = "campus_maintainance_request_system.wsgi.application"
ASGI_APPLICATION = "campus_maintainance_request_system.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "campus_maintenance"),
        "USER": os.environ.get("POSTGRES_USER", "campus"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@example.test")
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://localhost:8000").rstrip("/")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

PRIVATE_MEDIA_ROOT = Path(
    os.environ.get("PRIVATE_MEDIA_ROOT", BASE_DIR.parent / "private_uploads")
)
MAX_PHOTO_SIZE = int(os.environ.get("MAX_PHOTO_SIZE", str(5 * 1024 * 1024)))
MAX_PHOTO_WIDTH = int(os.environ.get("MAX_PHOTO_WIDTH", "4096"))
MAX_PHOTO_HEIGHT = int(os.environ.get("MAX_PHOTO_HEIGHT", "4096"))
MAX_PHOTO_PIXELS = int(os.environ.get("MAX_PHOTO_PIXELS", str(16 * 1024 * 1024)))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_PHOTO_SIZE + 1024 * 1024
REQUESTED_URGENCY_CHOICES = (
    ("LOW", "Low"),
    ("MEDIUM", "Medium"),
    ("HIGH", "High"),
)
PRIORITY_CHOICES = (
    ("LOW", "Low"),
    ("MEDIUM", "Medium"),
    ("HIGH", "High"),
    ("URGENT", "Urgent"),
)
AUTO_CLOSE_COMPLETED_DAYS = int(os.environ.get("AUTO_CLOSE_COMPLETED_DAYS", "30"))
REOPEN_AFTER_CLOSED_DAYS = int(os.environ.get("REOPEN_AFTER_CLOSED_DAYS", "60"))
TICKET_PREFIX = os.environ.get("TICKET_PREFIX", "MR")
SYSTEM_USER_EMAIL = os.environ.get("SYSTEM_USER_EMAIL", "system@campus.local")
