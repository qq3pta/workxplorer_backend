from rest_framework import serializers

from .models import Agreement


class AgreementDetailSerializer(serializers.ModelSerializer):
    offer_id = serializers.IntegerField(source="offer.id", read_only=True)
    cargo_id = serializers.IntegerField(source="offer.cargo.id", read_only=True)

    # ---------- ПОГРУЗКА ----------
    loading_city = serializers.CharField(source="offer.cargo.origin_city", read_only=True)
    loading_address = serializers.CharField(source="offer.cargo.origin_address", read_only=True)
    loading_date = serializers.DateField(source="offer.cargo.load_date", read_only=True)

    # ---------- РАЗГРУЗКА ----------
    unloading_city = serializers.CharField(source="offer.cargo.destination_city", read_only=True)
    unloading_address = serializers.CharField(
        source="offer.cargo.destination_address", read_only=True
    )
    unloading_date = serializers.DateField(source="offer.cargo.delivery_date", read_only=True)

    # ---------- ДЕТАЛИ ПОЕЗДКИ ----------
    total_distance_km = serializers.SerializerMethodField()
    travel_time = serializers.SerializerMethodField()

    class Meta:
        model = Agreement
        fields = (
            "id",
            "offer_id",
            "cargo_id",
            "status",
            "expires_at",
            "created_at",
            # --- ACCEPT ---
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
            # --- ПОГРУЗКА ---
            "loading_city",
            "loading_address",
            "loading_date",
            # --- РАЗГРУЗКА ---
            "unloading_city",
            "unloading_address",
            "unloading_date",
            # --- ДЕТАЛИ ---
            "total_distance_km",
            "travel_time",
        )

        read_only_fields = fields

    # ---------- METHODS ----------
    def get_total_distance_km(self, obj):
        order = getattr(obj, "order", None)
        return order.total_distance_km if order else None

    def get_travel_time(self, obj):
        order = getattr(obj, "order", None)
        return order.travel_time if order else None


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
