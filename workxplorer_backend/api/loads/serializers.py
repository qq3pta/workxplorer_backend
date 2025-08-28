from rest_framework import serializers
from .models import Cargo
from .choices import TransportType, ContactPref, ModerationStatus, Currency


class CargoPublishSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cargo
        fields = (
            "product", "description",
            "origin_address", "origin_city",
            "destination_address", "destination_city",
            "load_date", "delivery_date",
            "transport_type",
            "weight_kg",
            "price_value",
            "contact_pref", "is_hidden",
        )

    def validate(self, attrs):
        required = [
            "origin_address", "destination_address",
            "load_date", "transport_type",
            "weight_kg", "contact_pref",
        ]
        missing = [f for f in required if attrs.get(f) in (None, "", [])]
        if missing:
            raise serializers.ValidationError({f: "Обязательное поле по ТЗ 2.6.13" for f in missing})

        # справочники (избыточно, т.к. DRF сам валидирует choices, но оставим для явных сообщений)
        if attrs["transport_type"] not in TransportType.values:
            raise serializers.ValidationError({"transport_type": "Недопустимый тип транспорта"})
        if attrs["contact_pref"] not in ContactPref.values:
            raise serializers.ValidationError({"contact_pref": "Недопустимый способ связи"})
        if "price_currency" in attrs and attrs["price_currency"] not in Currency.values:
            raise serializers.ValidationError({"price_currency": "Недопустимая валюта"})

        # числа и даты
        if attrs["weight_kg"] <= 0:
            raise serializers.ValidationError({"weight_kg": "Вес должен быть > 0"})
        if attrs.get("price_value") is not None and attrs["price_value"] < 0:
            raise serializers.ValidationError({"price_value": "Цена не может быть отрицательной"})
        ld = attrs.get("load_date")
        dd = attrs.get("delivery_date")
        if dd and ld and dd < ld:
            raise serializers.ValidationError({"delivery_date": "Дата доставки не может быть раньше даты загрузки."})

        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        return Cargo.objects.create(
            customer=user,
            moderation_status=ModerationStatus.PENDING,
            **validated_data
        )


class CargoListSerializer(serializers.ModelSerializer):
    age_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Cargo
        fields = (
            "id",
            "product", "description",
            "origin_address", "origin_city",
            "destination_address", "destination_city",
            "load_date", "delivery_date",
            "transport_type",
            "weight_kg",
            "price_value",
            "contact_pref", "is_hidden",
            "moderation_status", "status",
            "age_minutes", "created_at", "refreshed_at",
        )
        read_only_fields = fields