from datetime import date, datetime
from decimal import Decimal
from typing import Any


def to_ws_safe(obj: Any):
    """
    Приводит payload к формату,
    безопасному для channels_redis / msgpack.
    """
    if isinstance(obj, Decimal):
        return str(obj)

    if isinstance(obj, (datetime, date)):  # noqa: UP038
        return obj.isoformat()

    if isinstance(obj, dict):
        return {k: to_ws_safe(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):  # noqa: UP038
        return [to_ws_safe(v) for v in obj]

    return obj
