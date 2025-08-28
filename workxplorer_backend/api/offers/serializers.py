from rest_framework import serializers

from api.loads.models import Cargo, CargoStatus
from api.loads.choices import Currency, ModerationStatus
from .models import Offer


class OfferCreateSerializer(serializers.ModelSerializer):
    cargo = serializers.PrimaryKeyRelatedField(queryset=Cargo.objects.all())

    class Meta:
        model = Offer
        fields = ("cargo", "price_value", "price_currency", "message")
        extra_kwargs = {
            "price_currency": {"required": False, "default": Currency.UZS},
            "message": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        user = self.context["request"].user
        cargo: Cargo = attrs["cargo"]

        # Запрет self-bid
        if cargo.customer_id == user.id:
            raise serializers.ValidationError({"cargo": "Нельзя сделать оффер на собственную заявку"})

        # Груз должен быть опубликован и доступен
        if cargo.is_hidden:
            raise serializers.ValidationError({"cargo": "Заявка скрыта"})
        if cargo.moderation_status != ModerationStatus.APPROVED:
            raise serializers.ValidationError({"cargo": "Заявка не прошла модерацию"})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"cargo": "Заявка уже не активна"})

        # Уникальность оффера на уровне приложения (помимо DB constraints)
        if Offer.objects.filter(cargo=cargo, carrier=user).exists():
            raise serializers.ValidationError({"cargo": "Вы уже отправили оффер на эту заявку"})

        # Доп. валидации значений
        price = attrs.get("price_value")
        if price is not None and price < 0:
            raise serializers.ValidationError({"price_value": "Цена не может быть отрицательной"})

        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        offer = Offer.objects.create(carrier=user, **validated_data)
        return offer


class OfferShortSerializer(serializers.ModelSerializer):
    cargo_origin = serializers.CharField(source="cargo.origin_city", read_only=True)
    cargo_destination = serializers.CharField(source="cargo.destination_city", read_only=True)
    cargo_customer_id = serializers.IntegerField(source="cargo.customer_id", read_only=True)

    class Meta:
        model = Offer
        fields = (
            "id",
            "cargo", "cargo_origin", "cargo_destination", "cargo_customer_id",
            "price_value", "price_currency",
            "message",
            "accepted_by_customer", "accepted_by_carrier",
            "is_active",
            "created_at",
        )
        read_only_fields = fields


class OfferDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = "__all__"
        read_only_fields = ("carrier", "accepted_by_customer", "accepted_by_carrier", "is_active")