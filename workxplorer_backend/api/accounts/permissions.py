from common.permissions import IsCarrier, IsCustomer, IsLogistic
from rest_framework.permissions import BasePermission

__all__ = [
    "IsLogistic",
    "IsCustomer",
    "IsCarrier",
    "IsAuthenticatedAndVerified",
]


def _is_user_verified(user) -> bool:
    """
    Универсальная проверка «верифицирован ли пользователь».
    Смотрим пару самых типичных флагов. Если хотя бы один явно True — ок.
    Если хотя бы один явно False — не ок.
    Если флагов нет вовсе — мягкий режим: считаем верифицированным,
    чтобы не ломать проект (можно сделать строгим — см. комментарий ниже).
    """
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
