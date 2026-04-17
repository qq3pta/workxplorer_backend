import logging
import time
from contextlib import contextmanager

from django.db import connection
from django.db.models import Prefetch

logger = logging.getLogger(__name__)


@contextmanager
def query_debugger(name="Query"):
    """
    Контекстный менеджер для отладки SQL запросов

    Usage:
        with query_debugger("My View"):
            # ... your code ...
    """
    queries_before = len(connection.queries)
    start_time = time.time()

    yield

    queries_after = len(connection.queries)
    queries_count = queries_after - queries_before
    duration = time.time() - start_time

    logger.debug(f"[{name}] Queries: {queries_count}, Time: {duration:.3f}s")

    if queries_count > 10:
        logger.warning(f"[{name}] Too many queries: {queries_count}")


def optimize_order_queryset(qs):
    """
    Оптимизирует queryset для Order с полной загрузкой связанных объектов
    """
    from api.orders.models import Order
    from api.ratings.models import UserRating

    return qs.select_related(
        "cargo",
        "customer",
        "carrier",
        "logistic",
        "created_by",
        "offer",
        "offer__carrier",
        "offer__logistic",
    ).prefetch_related(
        Prefetch(
            "documents",
            queryset=Order.documents.rel.related_model.objects.select_related("uploaded_by"),
        ),
        Prefetch("ratings", queryset=UserRating.objects.select_related("rated_by", "rated_user")),
        "payments",
    )


def optimize_offer_queryset(qs):
    """
    Оптимизирует queryset для Offer
    """
    return qs.select_related(
        "cargo",
        "cargo__customer",
        "carrier",
        "logistic",
        "intermediary",
    ).prefetch_related(
        "cargo__offers",
    )


def optimize_cargo_queryset(qs):
    """
    Оптимизирует queryset для Cargo
    """
    return qs.select_related(
        "customer",
        "created_by",
        "assigned_carrier",
        "chosen_offer",
    ).prefetch_related(
        "offers",
        "orders",
    )


def batch_update(model, instances, fields, batch_size=500):
    """
    Пакетное обновление объектов для улучшения производительности

    Args:
        model: Django модель
        instances: список объектов для обновления
        fields: список полей для обновления
        batch_size: размер пакета
    """
    for i in range(0, len(instances), batch_size):
        batch = instances[i : i + batch_size]
        model.objects.bulk_update(batch, fields, batch_size=batch_size)


def batch_create(model, data_list, batch_size=500):
    """
    Пакетное создание объектов

    Args:
        model: Django модель
        data_list: список словарей с данными
        batch_size: размер пакета

    Returns:
        список созданных объектов
    """
    created = []
    for i in range(0, len(data_list), batch_size):
        batch = data_list[i : i + batch_size]
        objects = [model(**data) for data in batch]
        created.extend(model.objects.bulk_create(objects, batch_size=batch_size))
    return created


def get_or_create_optimized(model, defaults=None, **lookup):
    """
    Оптимизированная версия get_or_create с меньшим количеством запросов
    """
    try:
        return model.objects.get(**lookup), False
    except model.DoesNotExist:
        params = dict(lookup, **(defaults or {}))
        try:
            return model.objects.create(**params), True
        except Exception:
            # Возможна race condition, пробуем получить еще раз
            try:
                return model.objects.get(**lookup), False
            except model.DoesNotExist:
                raise
