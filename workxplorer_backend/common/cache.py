"""
Кэширование для часто используемых данных
"""

import hashlib
import pickle
from functools import wraps

from django.core.cache import cache


def _generate_cache_key(key_prefix, func, args, kwargs):
    """
    Генерирует безопасный кэш-ключ с хэшированием
    Избегает проблем с длинными ключами
    """
    try:
        # Пытаемся сериализовать аргументы
        args_hash = hashlib.md5(pickle.dumps((args, sorted(kwargs.items())))).hexdigest()
    except (pickle.PicklingError, TypeError):
        # Если не получается - используем str
        args_hash = hashlib.md5(f"{str(args)}:{str(kwargs)}".encode()).hexdigest()

    return f"{key_prefix}:{func.__module__}.{func.__name__}:{args_hash}"


def cache_result(timeout=300, key_prefix="", version=None):
    """
    Декоратор для кэширования результатов функций

    Args:
        timeout: время жизни кэша в секундах (по умолчанию 5 минут)
        key_prefix: префикс для ключа кэша
        version: версия кэша (для инвалидации)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Генерируем безопасный ключ кэша
            cache_key = _generate_cache_key(key_prefix, func, args, kwargs)

            # Пытаемся получить из кэша
            result = cache.get(cache_key, version=version)

            if result is None:
                # Если в кэше нет, вычисляем
                result = func(*args, **kwargs)
                # Сохраняем в кэш только если результат не None
                if result is not None:
                    cache.set(cache_key, result, timeout, version=version)

            return result

        return wrapper

    return decorator


def invalidate_cache(key_prefix="", pattern=None):
    """
    Инвалидация кэша по префиксу или паттерну

    Args:
        key_prefix: префикс ключа для удаления
        pattern: паттерн для поиска ключей (если поддерживается backend)
    """
    if pattern:
        # Для Redis используем SCAN вместо KEYS (более безопасно)
        try:
            from django_redis import get_redis_connection

            conn = get_redis_connection("default")

            # Используем SCAN вместо KEYS для большой производительности
            cursor = 0
            keys_to_delete = []

            while True:
                cursor, keys = conn.scan(cursor, match=pattern, count=100)
                keys_to_delete.extend(keys)
                if cursor == 0:
                    break

            if keys_to_delete:
                # Удаляем пакетами по 1000
                for i in range(0, len(keys_to_delete), 1000):
                    batch = keys_to_delete[i : i + 1000]
                    conn.delete(*batch)

        except ImportError:
            # Если Redis не доступен
            pass
        except Exception as e:
            # Логируем ошибку, но не падаем
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Cache invalidation failed: {e}")

    elif key_prefix:
        try:
            from django_redis import get_redis_connection

            conn = get_redis_connection("default")
            invalidate_cache(pattern=f"{key_prefix}*")
        except ImportError:
            # Fallback для locmem cache
            try:
                if hasattr(cache, "_cache"):
                    keys_to_delete = [
                        key for key in cache._cache.keys() if key.startswith(key_prefix)
                    ]
                    cache.delete_many(keys_to_delete)
            except Exception:
                pass
