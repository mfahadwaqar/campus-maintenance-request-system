import os
from pathlib import Path

from campus_maintainance_request_system.dburl import database_settings

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

REOPEN_WINDOW_DAYS = 3

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "accounts.apps.AccountsConfig",
    "reports.apps.ReportsConfig",
    "assignments.apps.AssignmentsConfig",
    "notifications.apps.NotificationsConfig",
    "ps4.apps.Ps4Config",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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

DATABASES = {"default": database_settings(os.environ)}

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

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "reports.api_authentication.ApiSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# The React front end runs on its own origin (a different port on the same host).
# It sends the session cookie (credentials: "include") and an X-CSRFToken header.
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "FRONTEND_ORIGINS",
        "http://192.41.170.180:5173,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
CORS_ALLOWED_ORIGINS = FRONTEND_ORIGINS
CORS_ALLOW_CREDENTIALS = True
CORS_URLS_REGEX = r"^/(api|accounts)/.*$"
CSRF_TRUSTED_ORIGINS = list(FRONTEND_ORIGINS)
CSRF_FAILURE_VIEW = "accounts.api.csrf_failure"

API_SCHEMA_PATH = "api/schema/"
API_DOCS_PATH = "api/docs/"
API_SERVERS = [
    {"url": "http://192.41.170.180", "description": "CSIM server (deployed)"},
    {"url": "http://localhost:8000", "description": "Local development"},
]

SPECTACULAR_SETTINGS = {
    "TITLE": "Campus Maintenance Request API",
    "DESCRIPTION": "Session-authenticated API for maintenance reports and workflow.",
    "VERSION": "1.0.0",
    "SERVERS": API_SERVERS,
}

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
PHOTO_STORAGE = os.environ.get("PHOTO_STORAGE", "filesystem").lower()
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
TICKET_PREFIX = os.environ.get("TICKET_PREFIX", "MR")
SYSTEM_USER_EMAIL = os.environ.get("SYSTEM_USER_EMAIL", "system@campus.local")
