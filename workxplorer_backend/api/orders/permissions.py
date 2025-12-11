from rest_framework.permissions import BasePermission


class IsOrderParticipant(BasePermission):
    """
    Доступ:
    • LOGISTIC — только заказы, созданные им или связанные с его грузами
    • CUSTOMER — только свои
    • CARRIER — только свои
    • STAFF — всё
    """

    def has_permission(self, request, view):
        # Разрешаем accept-invite для любого авторизованного перевозчика
        if getattr(view, "action", None) == "accept_invite":
            return request.user.is_authenticated

        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        u = request.user
        role = getattr(u, "role", None)
        action = getattr(view, "action", None)

        # Разрешаем accept-invite, даже если carrier_id пустой
        if action == "accept_invite" and role == "CARRIER":
            return True

        # STAFF может всё
        if getattr(u, "is_staff", False) or getattr(u, "is_superuser", False):
            return True

        # LOGISTIC
        if role == "LOGISTIC":
            # оффер может отсутствовать → защищаемся try/except
            offer = getattr(obj, "offer", None)

            return (
                obj.logistic_id == u.id
                or obj.created_by_id == u.id
                or obj.cargo.created_by_id == u.id
                or obj.customer_id == u.id
                or (
                    offer
                    and (
                        getattr(offer, "logistic_id", None) == u.id
                        or getattr(offer, "intermediary_id", None) == u.id
                    )
                )
            )

        # CUSTOMER
        if role == "CUSTOMER":
            return obj.customer_id == u.id

        # CARRIER
        if role == "CARRIER":
            return obj.carrier_id == u.id

        return False
