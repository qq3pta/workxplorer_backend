# ====== BUILDER ======
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /app

# Системные зависимости для сборки (GDAL/GEOS/PROJ + pg headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl libpq-dev \
    gdal-bin libgdal-dev libproj-dev libgeos-dev binutils \
 && rm -rf /var/lib/apt/lists/*

# Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Установка зависимостей проекта
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-interaction --no-ansi --only main

# Код
COPY . .

# ====== RUNTIME ======
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Рантайм-библиотеки (важно: GDAL/GEOS/PROJ в рантайме тоже нужны)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gdal-bin libgdal-dev libproj-dev libgeos-dev binutils \
 && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN useradd -m appuser
USER appuser

# Копируем виртуалку и код
COPY --chown=appuser:appuser --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser . .

EXPOSE 8000

# Gunicorn
CMD ["gunicorn","core.wsgi:application","--chdir","workxplorer_backend","--bind","0.0.0.0:8000","--workers","3","--timeout","120"]