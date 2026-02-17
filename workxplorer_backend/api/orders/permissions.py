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
        if getattr(view, "action", None) == "accept_invite":
            return request.user.is_authenticated
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        u = request.user
        role = getattr(u, "role", None)
        action = getattr(view, "action", None)

        if action == "accept_invite" and role == "CARRIER":
            return True

        # STAFF может всё
        if getattr(u, "is_staff", False) or getattr(u, "is_superuser", False):
            return True

        # LOGISTIC
        if role == "LOGISTIC":
            # логист может приглашать в свои заказы
            if action == "invite_by_id":
                return obj.created_by_id == u.id

            offer = getattr(obj, "offer", None)

            return (
                obj.logistic_id == u.id
                or obj.created_by_id == u.id
                or obj.cargo.created_by_id == u.id
                # 🔹 ВАЖНО: логист создал заказ, но ещё не проставился
                or (obj.created_by_id == u.id and obj.logistic_id is None)
                # 🔹 логист приглашает перевозчика (invite stage)
                or (obj.invited_carrier_id is not None and obj.created_by_id == u.id)
                # 🔹 логист в offer
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
