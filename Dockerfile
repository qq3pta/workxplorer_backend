FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=off \
    POETRY_VERSION=1.8.3

# GeoDjango системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Poetry
RUN pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock* /app/

RUN poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi

COPY workxplorer_backend /app/workxplorer_backend

RUN python -c "print('Docker build sanity ✓')"

EXPOSE 8000

# Gunicorn
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]