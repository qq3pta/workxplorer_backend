from rest_framework.permissions import BasePermission


class IsAgreementParticipant(BasePermission):
    """
    Доступ только участникам соглашения:
    CUSTOMER / CARRIER / LOGISTIC
    """

    def has_object_permission(self, request, view, obj):
        u = request.user
        offer = obj.offer

        if not u or not u.is_authenticated:
            return False

        if u.role == "CUSTOMER":
            return u.id == offer.cargo.customer_id

        if u.role == "CARRIER":
            return u.id == offer.carrier_id

        if u.role == "LOGISTIC":
            return (
                u.id == offer.logistic_id
                or u.id == offer.intermediary_id
                or u.id == offer.cargo.created_by_id
            )

        return False
