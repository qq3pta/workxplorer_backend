from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from .models import UserRole

DEFAULT_DEMO_REQUEST_LIMIT = 5


def get_demo_request_limit(user) -> int:
    limit = getattr(user, "demo_request_limit", DEFAULT_DEMO_REQUEST_LIMIT)
    return max(int(limit or DEFAULT_DEMO_REQUEST_LIMIT), 0)


def has_signed_contract_access(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and (
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or getattr(user, "has_signed_contract", False)
        )
    )


def user_role(user) -> str:
    return (getattr(user, "role", "") or "").upper()


def demo_published_cargo_count(user) -> int:
    from api.loads.models import Cargo

    return Cargo.objects.filter(Q(customer=user) | Q(created_by=user)).distinct().count()


def demo_transport_order_count(user) -> int:
    from api.orders.models import Order

    return (
        Order.objects.filter(Q(carrier=user) | Q(logistic=user))
        .exclude(status="canceled")
        .distinct()
        .count()
    )


def ensure_can_access_paid_feature(user, feature_name: str) -> None:
    if has_signed_contract_access(user):
        return
    raise PermissionDenied(
        f"{feature_name} available after contract signing. Contact support to unlock access."
    )


def ensure_can_publish_demo_cargo(user) -> None:
    if has_signed_contract_access(user):
        return

    role = user_role(user)
    if role not in {UserRole.CUSTOMER, UserRole.LOGISTIC}:
        return

    limit = get_demo_request_limit(user)
    used = demo_published_cargo_count(user)
    if used >= limit:
        raise PermissionDenied(
            f"Demo limit reached: you can publish only {limit} cargo requests before contract signing."
        )


def ensure_can_take_demo_transport(user) -> None:
    if has_signed_contract_access(user):
        return

    role = user_role(user)
    if role not in {UserRole.CARRIER, UserRole.LOGISTIC}:
        return

    limit = get_demo_request_limit(user)
    used = demo_transport_order_count(user)
    if used >= limit:
        raise PermissionDenied(
            f"Demo limit reached: you can take only {limit} transport requests before contract signing."
        )
