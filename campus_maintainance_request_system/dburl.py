"""Database settings from the environment: one DATABASE_URL (Neon, Render) or separate POSTGRES_* values."""

from urllib.parse import parse_qs, unquote, urlparse

PASSED_THROUGH_OPTIONS = ("sslmode", "channel_binding")


def database_settings(environ):
    config = {"ENGINE": "django.db.backends.postgresql", "CONN_MAX_AGE": 60}
    url = environ.get("DATABASE_URL", "").strip()
    if url:
        parts = urlparse(url)
        if parts.scheme not in ("postgres", "postgresql"):
            raise ValueError("DATABASE_URL must start with postgresql://")
        config.update(
            NAME=unquote(parts.path.lstrip("/")),
            USER=unquote(parts.username or ""),
            PASSWORD=unquote(parts.password or ""),
            HOST=parts.hostname or "",
            PORT=str(parts.port or 5432),
        )
        query = parse_qs(parts.query)
        options = {key: query[key][0] for key in PASSED_THROUGH_OPTIONS if key in query}
    else:
        config.update(
            NAME=environ.get("POSTGRES_DB", "campus_maintenance"),
            USER=environ.get("POSTGRES_USER", "campus"),
            PASSWORD=environ.get("POSTGRES_PASSWORD", ""),
            HOST=environ.get("POSTGRES_HOST", "localhost"),
            PORT=environ.get("POSTGRES_PORT", "5432"),
        )
        options = {"sslmode": environ["POSTGRES_SSLMODE"]} if environ.get("POSTGRES_SSLMODE") else {}
    if options:
        config["OPTIONS"] = options
    return config
