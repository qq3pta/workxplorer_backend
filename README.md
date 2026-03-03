# KAD — Биржа грузоперевозок

Django/DRF backend для онлайн-платформы грузоперевозок с поддержкой WebSocket, real-time уведомлений, геосервисов и интеграций с внешними сервисами.

**Язык**: ru-RU · **Часовой пояс**: Asia/Tashkent · **Python**: 3.11-3.12

---

## Содержание

- [Стек](#стек)
- [Структура проекта](#структура-проекта)
- [Быстрый старт](#быстрый-старт)
  - [Через Docker Compose](#через-docker-compose)
  - [Локально (Poetry)](#локально-poetry)
- [.env — переменные окружения](#env--переменные-окружения)
- [Миграции, статик, медиа](#миграции-статик-медиа)
- [Документация API](#документация-api)
- [Аутентификация и роли](#аутентификация-и-роли)
- [Модули и эндпоинты](#модули-и-эндпоинты)
- [Примеры запросов](#примеры-запросов)
- [CI/CD](#cicd)
- [Продакшен-заметки](#продакшен-заметки)
- [Лицензия](#лицензия)

---

## Стек

### Backend
- **Python** 3.11-3.12
- **Django** 4.2+ с **Django REST Framework** 3.14+
- **Django Channels** 4.3+ (WebSocket, real-time коммуникация)
- **Daphne** (ASGI сервер)

### Базы данных и кэш
- **PostgreSQL** с расширением **PostGIS** 16-3.4 (геопоиск, расчёт расстояний)
- **Redis** 6+ (Channels layer, кэширование, Celery broker)

### Аутентификация и безопасность
- **JWT** через `djangorestframework-simplejwt` 5.5+
- **Firebase Admin SDK** (push-уведомления)
- **Twilio** (SMS-уведомления)

### API и документация
- **drf-spectacular** (OpenAPI 3.0 / Swagger UI)
- **django-filter**, **django-cors-headers**

### Асинхронные задачи
- **Celery** 5.4+ с Redis broker

### Дополнительно
- **Sentry** (мониторинг ошибок)
- **Gunicorn** / **Whitenoise** (статика)
- **Docker Compose** (оркестрация)

---

## Структура проекта

```bash
workxplorer_backend/
├── workxplorer_backend/
│   ├── api/
│   │   ├── accounts/       # Регистрация, аутентификация (JWT), роли пользователей
│   │   ├── agreements/     # Договоры и соглашения между сторонами
│   │   ├── geo/            # Геосервисы (координаты, PostGIS, расчёт расстояний)
│   │   ├── loads/          # Грузы и заявки на перевозку
│   │   ├── notifications/  # Real-time уведомления (WebSocket, Firebase, SMS)
│   │   ├── offers/         # Предложения перевозчиков на заявки
│   │   ├── orders/         # Заказы и жизненный цикл перевозки
│   │   ├── payments/       # Платежи, транзакции, балансы
│   │   ├── ratings/        # Рейтинги и отзывы пользователей
│   │   ├── routing/        # Маршруты и оптимизация путей
│   │   ├── search/         # Поиск и фильтрация грузов/транспорта
│   │   └── support/        # Поддержка и обращения пользователей
│   ├── common/             # Общие утилиты, базовые классы, миксины
│   ├── core/
│   │   ├── settings/       # base.py / dev.py / prod.py
│   │   ├── urls.py         # Маршруты API, schema, docs, health
│   │   ├── asgi.py         # ASGI + Channels для WebSocket
│   │   ├── wsgi.py         # WSGI для production
│   │   └── health.py       # Health check endpoint
│   ├── media/              # Загружаемые пользователями файлы
│   ├── static/             # Статические файлы
│   ├── manage.py
│   ├── example.env         # Пример переменных окружения
│   └── schema.yaml         # OpenAPI спецификация
├── pyproject.toml          # Poetry конфигурация и зависимости
├── poetry.lock
├── Dockerfile
├── Dockerfile.base
├── docker-compose.yml      # PostgreSQL + Redis + Web (Daphne)
├── .pre-commit-config.yaml
└── README.md
```

---

## Быстрый старт

### Через Docker Compose

```bash
cp back/example.env .env
docker compose up --build
```

### Локально (Poetry)

```bash
poetry install
cp back/example.env back/.env
poetry run python back/manage.py migrate
poetry run python back/manage.py runserver
```

---

## .env — переменные окружения

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`

---

## Миграции, статик, медиа

```bash
poetry run python back/manage.py migrate
poetry run python back/manage.py collectstatic --noinput
```

---

## Документация API

- `/api/docs/`
- `/api/schema/`

---

## Аутентификация и роли

- JWT Bearer token
- `/api/auth/login/`, `/api/auth/refresh/`, `/api/auth/me/`
- `customer`, `carrier`, `logistic`, `admin`

---

## Модули и эндпоинты

- `/api/auth/`, `/api/loads/`, `/api/search/`
- `/api/offers/`, `/api/orders/`, `/api/geo/`
- `/api/notifications/`, `/api/payments/`, `/api/support/`

WebSocket:
- `ws://<host>/ws/notifications/?token=<access_token>`
- `ws://<host>/ws/loads?token=<access_token>`

---

## Примеры запросов

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret"}'
```

---

## CI/CD

`check`, `ruff`, `pytest`

---

## Продакшен заметки

- `core.settings.prod`
- CORS/CSRF + HTTPS

---

## Лицензия

<Лицензия проекта>