from rest_framework import serializers

from .models import Agreement


class AgreementDetailSerializer(serializers.ModelSerializer):
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
            "created_at",
            "accepted_by_customer",
            "accepted_by_carrier",
            "accepted_by_logistic",
            # --- CUSTOMER ---
            "customer_id",
            "customer_full_name",
            "customer_email",
            "customer_phone",
            "customer_registered_at",
            # --- CARRIER ---
            "carrier_id",
            "carrier_full_name",
            "carrier_email",
            "carrier_phone",
            "carrier_registered_at",
            # --- LOGISTIC ---
            "logistic_id",
            "logistic_full_name",
            "logistic_email",
            "logistic_phone",
            "logistic_registered_at",
        )
        read_only_fields = fields


class AgreementActionSerializer(serializers.Serializer):
    """Пустой body для accept / reject"""

    pass


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
