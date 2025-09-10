# ===== base =====
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gdal-bin libgdal-dev libproj-dev libgeos-dev binutils \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# ===== builder =====
FROM base AS builder
ARG POETRY_VERSION=1.8.3
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-interaction --no-ansi

# (опционально) прогреть компиляцию зависимостей
COPY workxplorer_backend ./workxplorer_backend

# ===== runtime =====
FROM base AS runtime
RUN useradd -m appuser
USER appuser
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . .
ENV DJANGO_SETTINGS_MODULE=core.settings.prod
EXPOSE 8000
CMD ["gunicorn", "core.wsgi:application", "--chdir", "workxplorer_backend", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]