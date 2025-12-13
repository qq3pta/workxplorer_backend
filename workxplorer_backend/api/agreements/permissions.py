from rest_framework.permissions import BasePermission


class IsAgreementParticipant(BasePermission):
    """
    Доступ только участникам соглашения:
    CUSTOMER / CARRIER / LOGISTIC
    """

    def has_object_permission(self, request, view, obj):
        u = request.user
        offer = obj.offer
        cargo = offer.cargo

        if not u or not u.is_authenticated:
            return False

        return (
            u.id == cargo.customer_id  # обычный заказчик
            or u.id == cargo.created_by_id  # логист-заказчик (кейс 2)
            or u.id == offer.carrier_id  # перевозчик
            or u.id == offer.logistic_id  # логист-участник
            or u.id == offer.intermediary_id  # логист-посредник
        )
