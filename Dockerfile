FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=campus_maintainance_request_system.settings.prod

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home app \
    && mkdir -p /app/staticfiles /private_uploads \
    && chown -R app:app /app /private_uploads

COPY --chown=app:app . .
USER app

EXPOSE 8000
CMD ["gunicorn", "campus_maintainance_request_system.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
