from rest_framework.permissions import BasePermission


class IsOfferParticipant(BasePermission):
    """
    Доступ к офферу имеют только участники сделки
    """

    def has_object_permission(self, request, view, offer):
        u = request.user
        cargo = offer.cargo

        if not u or not u.is_authenticated:
            return False

        return u.id in (
            cargo.customer_id,  # заказчик
            cargo.created_by_id,  # логист-создатель заказа
            offer.carrier_id,  # перевозчик
            offer.logistic_id,  # логист оффера
            offer.intermediary_id,  # логист-посредник
        )
