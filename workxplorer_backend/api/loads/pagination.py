from rest_framework.pagination import PageNumberPagination
from django.core.cache import cache
from django.utils.encoding import force_str


class OptimizedLoadsPagination(PageNumberPagination):
    """
    Оптимизированная пагинация с кэшированием count запросов
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_count(self, queryset):
        """
        Кэширование count запросов для улучшения производительности
        """
        # Генерируем ключ кэша на основе SQL запроса
        query_str = force_str(queryset.query)
        cache_key = f"loads_count:{hash(query_str)}"

        # Пытаемся получить из кэша
        count = cache.get(cache_key)

        if count is None:
            # Если нет в кэше, выполняем запрос
            count = super().get_count(queryset)
            # Кэшируем на 60 секунд (короткое время для актуальности)
            cache.set(cache_key, count, 60)

        return count


class LoadsBoardPagination(PageNumberPagination):
    """
    Пагинация для доски грузов (меньше записей на странице)
    """

    page_size = 15
    page_size_query_param = "page_size"
    max_page_size = 50
