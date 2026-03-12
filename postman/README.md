# Postman: старт тестирования API

## Что добавлено
- `endpoints.json` - полная коллекция HTTP эндпоинтов по модулям.
- `environment.json` - окружение с переменными для URL, токенов и ID.

## Как запустить
1. Поднимите backend (`http://localhost:8000`).
2. Импортируйте в Postman оба файла из папки `postman/`.
3. Выберите окружение `KAD Local`.
4. Заполните `user_email` и `user_password` валидным пользователем.
5. Сначала выполните `POST /api/auth/login/`:
   - токены `access`/`refresh` сохраняются автоматически в environment.
6. Запускайте GET-листы:
   - `GET /api/loads/mine/`, `GET /api/offers/`, `GET /api/orders/`, `GET /api/notifications/`, `GET /api/agreements/agreements/`, `GET /api/ratings/ratings/`
   - первые `id/uuid` из ответа сохраняются автоматически в environment.
7. После этого запускайте detail/action/write endpoint'ы.

## Что покрывает эта версия
- Полный список HTTP endpoint'ов текущего API.
- Автосохранение JWT после login/refresh.
- Автосохранение базовых ID/UUID из list-запросов.
- Отдельные endpoint'ы всё равно требуют реальных данных (например `invite_token`, upload файлов и т.д.).

## Дальше по этапам
1. Расширить коллекцию на write-сценарии (create/update/status actions) с тестовыми данными.
2. Добавить запуск через Newman (`npm` script + CI шаг).
3. Зафиксировать контракты и перенести критичные сценарии в `pytest` (API integration tests).
