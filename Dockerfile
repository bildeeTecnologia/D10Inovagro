FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_USE_WHITENOISE=1

WORKDIR /app

RUN addgroup --system django && adduser --system --ingroup django django

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Build static assets without a database connection or any runtime secrets.
RUN DATABASE_URL= \
    DJANGO_DEBUG=0 \
    DJANGO_SECRET_KEY=build-only-not-runtime-secret-abcdefghijklmnopqrstuvwxyz-0123456789 \
    DJANGO_COLLABORATOR_ID_KEY=build-only-not-runtime-id-key-abcdefghijklmnopqrstuvwxyz-0123456789 \
    DJANGO_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

RUN chown -R django:django /app
USER django

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
