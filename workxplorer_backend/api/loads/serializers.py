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
            "price_value", "price_currency",
            "contact_pref", "is_hidden",
        )

    def _val_or_instance(self, attrs, name):
        """Берём значение из attrs, а если апдейт и поля нет — из instance."""
        if name in attrs:
            return attrs[name]
        if self.instance is not None:
            return getattr(self.instance, name, None)
        return None

    def validate(self, attrs):
        # обязательные по ТЗ — проверяем только на создании; на апдейте допускаем частичные изменения
        required = [
            "origin_address", "destination_address",
            "load_date", "transport_type",
            "weight_kg", "contact_pref",
        ]
        if self.instance is None:
            missing = [f for f in required if attrs.get(f) in (None, "", [])]
            if missing:
                raise serializers.ValidationError({f: "Обязательное поле по ТЗ 2.6.13" for f in missing})

        # справочники: даём дружелюбные сообщения (DRF и так валидирует choices)
        transport_type = self._val_or_instance(attrs, "transport_type")
        contact_pref   = self._val_or_instance(attrs, "contact_pref")
        price_currency = self._val_or_instance(attrs, "price_currency")

        if transport_type is not None and transport_type not in TransportType.values:
            raise serializers.ValidationError({"transport_type": "Недопустимый тип транспорта"})
        if contact_pref is not None and contact_pref not in ContactPref.values:
            raise serializers.ValidationError({"contact_pref": "Недопустимый способ связи"})
        if price_currency is not None and price_currency not in Currency.values:
            raise serializers.ValidationError({"price_currency": "Недопустимая валюта"})

        # числа
        weight = self._val_or_instance(attrs, "weight_kg")
        if weight is not None and weight <= 0:
            raise serializers.ValidationError({"weight_kg": "Вес должен быть > 0"})
        price = self._val_or_instance(attrs, "price_value")
        if price is not None and price < 0:
            raise serializers.ValidationError({"price_value": "Цена не может быть отрицательной"})

        # даты
        ld = self._val_or_instance(attrs, "load_date")
        dd = self._val_or_instance(attrs, "delivery_date")
        if dd and ld and dd < ld:
            raise serializers.ValidationError({"delivery_date": "Дата доставки не может быть раньше даты загрузки."})

        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        # владелец — текущий пользователь; премодерация — pending
        return Cargo.objects.create(
            customer=user,
            moderation_status=ModerationStatus.PENDING,
            **validated_data,
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
            "price_value", "price_currency",
            "contact_pref", "is_hidden",
            "moderation_status", "status",
            "age_minutes", "created_at", "refreshed_at",
        )
        read_only_fields = fields