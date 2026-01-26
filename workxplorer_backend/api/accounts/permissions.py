from common.permissions import IsCarrier, IsCustomer, IsLogistic
from rest_framework.permissions import BasePermission

__all__ = [
    "IsLogistic",
    "IsCustomer",
    "IsCarrier",
    "IsAuthenticatedAndVerified",
    "IsCarrierOrLogistic",
    "IsCustomerOrLogistic",
    "IsCustomerOrCarrierOrLogistic",
]


def _is_user_verified(user) -> bool:
    return bool(getattr(user, "is_phone_verified", False))


class IsAuthenticatedAndVerified(BasePermission):
    message = "Требуется авторизация и подтверждённый аккаунт."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and _is_user_verified(user))


class IsCarrierOrLogistic(BasePermission):
    """
    Разрешает доступ, если пользователь — Перевозчик ИЛИ Логист.
    Делегируем проверку существующим классам из common.permissions.
    """

    def has_permission(self, request, view) -> bool:
        return IsCarrier().has_permission(request, view) or IsLogistic().has_permission(
            request, view
        )


class IsCustomerOrLogistic(BasePermission):
    """
    Разрешает доступ Заказчику (грузовладельцу) ИЛИ Логисту.
    Удобно для публикации/редактирования заявок, если по продукту логист тоже может создавать.
    """

    message = "Доступ только для Заказчика или Логиста."

    def has_permission(self, request, view) -> bool:
        return IsCustomer().has_permission(request, view) or IsLogistic().has_permission(
            request, view
        )


class IsCustomerOrCarrierOrLogistic(BasePermission):
    message = "Доступ только для Заказчика, Перевозчика или Логиста."

    def has_permission(self, request, view) -> bool:
        return (
            IsCustomer().has_permission(request, view)
            or IsCarrier().has_permission(request, view)
            or IsLogistic().has_permission(request, view)
        )
