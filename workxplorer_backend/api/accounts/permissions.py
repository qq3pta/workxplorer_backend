from common.permissions import IsCarrier, IsCustomer, IsLogistic
from rest_framework.permissions import BasePermission

__all__ = [
    "IsLogistic",
    "IsCustomer",
    "IsCarrier",
    "IsAuthenticatedAndVerified",
    "IsCarrierOrLogistic",
    "IsCustomerOrLogistic",
]


def _is_user_verified(user) -> bool:
    candidate_flags = (
        "is_verified",
        "email_verified",
        "is_email_verified",
        "phone_verified",
        "is_phone_verified",
    )
    saw_any_flag = False
    for name in candidate_flags:
        val = getattr(user, name, None)
        if val is True:
            return True
        if val is False:
            saw_any_flag = True
    return False if saw_any_flag else True


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
        return IsCustomer().has_permission(request, view) or IsLogistic().has_permission(request, view)