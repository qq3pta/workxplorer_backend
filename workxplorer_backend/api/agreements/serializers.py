from rest_framework import serializers
from .models import Agreement


class AgreementListSerializer(serializers.ModelSerializer):
    offer_id = serializers.IntegerField(source="offer.id", read_only=True)
    cargo_id = serializers.IntegerField(source="offer.cargo.id", read_only=True)

    class Meta:
        model = Agreement
        fields = (
            "id",
            "offer_id",
            "cargo_id",
            "status",
            "expires_at",
            "accepted_by_customer",
            "accepted_by_carrier",
            "accepted_by_logistic",
            "created_at",
        )
        read_only_fields = fields


class AgreementActionSerializer(serializers.Serializer):
    """Пустой body для accept / reject"""

    pass
