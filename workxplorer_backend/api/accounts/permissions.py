from rest_framework.permissions import BasePermission
from .models import UserRole


def _role(user):
    return getattr(user, "role", None)


class IsLogistic(BasePermission):
    """Доступ только логисту."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and _role(request.user) == UserRole.LOGISTIC)


class IsCustomer(BasePermission):
    """Доступ заказчику, а также логисту (полный доступ по ТЗ)."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return _role(request.user) in (UserRole.CUSTOMER, UserRole.LOGISTIC)


class IsCarrier(BasePermission):
    """Доступ перевозчику, а также логисту (полный доступ по ТЗ)."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return _role(request.user) in (UserRole.CARRIER, UserRole.LOGISTIC)