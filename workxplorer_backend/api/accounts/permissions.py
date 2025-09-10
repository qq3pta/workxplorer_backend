from rest_framework.permissions import BasePermission

from .models import UserRole


def _is_verified(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "is_email_verified", False))


class IsAuthenticatedAndVerified(BasePermission):
    """Любая роль, но пользователь авторизован и подтвердил e-mail."""

    def has_permission(self, request, view):
        return _is_verified(request.user)


class IsLogistic(BasePermission):
    """Только логист (полный доступ по ТЗ)."""

    def has_permission(self, request, view):
        u = request.user
        return _is_verified(u) and u.role == UserRole.LOGISTIC


class IsCustomer(BasePermission):
    """Доступ для Заказчика; Логист также проходит (полный доступ по ТЗ)."""

    def has_permission(self, request, view):
        u = request.user
        return _is_verified(u) and (u.role == UserRole.CUSTOMER or u.role == UserRole.LOGISTIC)


class IsCarrier(BasePermission):
    """Доступ для Перевозчика; Логист также проходит (полный доступ по ТЗ)."""

    def has_permission(self, request, view):
        u = request.user
        return _is_verified(u) and (u.role == UserRole.CARRIER or u.role == UserRole.LOGISTIC)


class RolePermission(BasePermission):
    """
    Универсально: во вьюхе укажи allowed_roles = [UserRole.CUSTOMER, ...]
    Логист всегда проходит.
    """

    def has_permission(self, request, view):
        u = request.user
        if not _is_verified(u):
            return False
        if u.role == UserRole.LOGISTIC:
            return True
        allowed = getattr(view, "allowed_roles", None)
        return True if not allowed else u.role in allowed
