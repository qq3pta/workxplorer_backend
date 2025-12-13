from rest_framework.permissions import BasePermission


class IsOfferParticipant(BasePermission):
    """
    Доступ к офферу имеют только участники сделки
    """

    def has_object_permission(self, request, view, offer):
        u = request.user
        cargo = offer.cargo

        print("\n[PERMISSION DEBUG]")
        print("user.id =", getattr(u, "id", None), "role =", getattr(u, "role", None))
        print("cargo.customer_id =", cargo.customer_id)
        print("cargo.created_by_id =", cargo.created_by_id)
        print("offer.logistic_id =", offer.logistic_id)
        print("offer.intermediary_id =", offer.intermediary_id)
        print("offer.carrier_id =", offer.carrier_id)

        if not u or not u.is_authenticated:
            print("❌ not authenticated")
            return False

        allowed = u.id in (
            cargo.customer_id,
            cargo.created_by_id,
            offer.carrier_id,
            offer.logistic_id,
            offer.intermediary_id,
        )

        print("PERMISSION RESULT =", allowed)
        return allowed
