"""
Middleware для мониторинга производительности запросов
"""

import time
import logging
from django.db import connection
from django.conf import settings

logger = logging.getLogger(__name__)


class QueryCountDebugMiddleware:
    """
    Middleware для отслеживания количества SQL запросов и времени выполнения
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Сбрасываем счетчик запросов
        queries_before = len(connection.queries)
        start_time = time.time()

        # Обрабатываем запрос
        response = self.get_response(request)

        # Подсчитываем статистику
        queries_after = len(connection.queries)
        queries_count = queries_after - queries_before
        duration = time.time() - start_time

        # Добавляем заголовки в response (только для DEBUG)
        if settings.DEBUG:
            response["X-DB-Queries"] = str(queries_count)
            response["X-Response-Time"] = f"{duration:.3f}s"

        # Логируем медленные запросы
        if duration > 1.0:  # Медленнее 1 секунды
            logger.warning(
                f"Slow request: {request.method} {request.path} "
                f"- {queries_count} queries in {duration:.3f}s"
            )
        elif queries_count > 20:  # Много запросов
            logger.warning(
                f"Too many queries: {request.method} {request.path} "
                f"- {queries_count} queries in {duration:.3f}s"
            )

        return response
