from rest_framework.permissions import BasePermission


class IsOrderParticipant(BasePermission):
    """
    Доступ:
    • LOGISTIC — только заказы, созданные им (created_by)
    • CUSTOMER — только свои (customer)
    • CARRIER — только свои (carrier)
    • STAFF — всё
    """

    def has_permission(self, request, view):
        # Разрешаем accept-invite для любого авторизованного перевозчика
        if view.action == "accept_invite":
            return request.user.is_authenticated

        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        u = request.user
        role = getattr(u, "role", None)

        # Разрешаем accept-invite, даже если carrier_id ещё пустой
        if view.action == "accept_invite" and role == "CARRIER":
            return True

        if getattr(u, "is_staff", False) or getattr(u, "is_superuser", False):
            return True

        if role == "LOGISTIC":
            return (
                obj.logistic_id == u.id
                or obj.created_by_id == u.id
                or obj.cargo.created_by_id == u.id
                or (
                    obj.offer
                    and (obj.offer.logistic_id == u.id or obj.offer.intermediary_id == u.id)
                )
                or obj.customer_id == u.id
            )

        if role == "CUSTOMER":
            return obj.customer_id == u.id

        if role == "CARRIER":
            return obj.carrier_id == u.id

        return False
