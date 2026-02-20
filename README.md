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