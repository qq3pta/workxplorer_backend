from __future__ import annotations

from decimal import Decimal
from typing import Any

from api.loads.choices import Currency, ModerationStatus
from api.loads.models import Cargo, CargoStatus
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Offer

User = get_user_model()


class OfferCreateSerializer(serializers.ModelSerializer):
    """
    Создание оффера ПЕРЕВОЗЧИКОМ на чужую заявку.
    """

    cargo = serializers.PrimaryKeyRelatedField(queryset=Cargo.objects.all())
    price_value = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0.00")
    )
    price_currency = serializers.ChoiceField(
        choices=Currency.choices, required=False, default=Currency.UZS
    )
    message = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Offer
        fields = ("cargo", "price_value", "price_currency", "message")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        user = self.context["request"].user
        cargo: Cargo = attrs["cargo"]

        if cargo.customer_id == user.id:
            raise serializers.ValidationError(
                {"cargo": "Нельзя сделать оффер на собственную заявку."}
            )

        # Груз должен быть опубликован и доступен
        if getattr(cargo, "is_hidden", False):
            raise serializers.ValidationError({"cargo": "Заявка скрыта."})
        if cargo.moderation_status != ModerationStatus.APPROVED:
            raise serializers.ValidationError({"cargo": "Заявка не прошла модерацию."})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"cargo": "Заявка уже не активна."})

        # Только один активный оффер на пару cargo-carrier
        if Offer.objects.filter(cargo=cargo, carrier=user, is_active=True).exists():
            raise serializers.ValidationError(
                {"cargo": "У вас уже есть активный оффер на эту заявку."}
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> Offer:
        user = self.context["request"].user
        return Offer.objects.create(
            carrier=user,
            initiator=Offer.Initiator.CARRIER,
            **validated_data,
        )


class OfferInviteSerializer(serializers.Serializer):
    """
    Инвайт от ЗАКАЗЧИКА конкретному перевозчику.
    """

    cargo = serializers.PrimaryKeyRelatedField(queryset=Cargo.objects.all())
    carrier_id = serializers.PrimaryKeyRelatedField(source="carrier", queryset=User.objects.all())
    price_value = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0.00")
    )
    price_currency = serializers.ChoiceField(choices=Currency.choices, default=Currency.UZS)
    message = serializers.CharField(allow_blank=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        user = self.context["request"].user
        cargo: Cargo = attrs["cargo"]
        carrier: User = attrs["carrier"]

        # Права: только владелец груза (или логист, если у вас такая роль есть)
        if cargo.customer_id != user.id and not getattr(user, "is_logistic", False):
            raise serializers.ValidationError({"cargo": "Можно приглашать только на свою заявку."})

        if carrier.id == user.id:
            raise serializers.ValidationError({"carrier_id": "Нельзя приглашать самого себя."})

        # Только активные и одобренные заявки
        if getattr(cargo, "is_hidden", False):
            raise serializers.ValidationError({"cargo": "Заявка скрыта."})
        if cargo.moderation_status != ModerationStatus.APPROVED:
            raise serializers.ValidationError({"cargo": "Заявка не прошла модерацию."})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"cargo": "Заявка не активна."})

        # Один активный оффер на пару cargo-carrier
        if Offer.objects.filter(cargo=cargo, carrier=carrier, is_active=True).exists():
            raise serializers.ValidationError(
                {"carrier_id": "Этому перевозчику уже отправлено активное предложение."}
            )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Offer:
        return Offer.objects.create(
            initiator=Offer.Initiator.CUSTOMER,
            **validated_data,
        )


class OfferShortSerializer(serializers.ModelSerializer):
    """
    Короткая карточка оффера для списков.
    """

    cargo_uuid = serializers.UUIDField(source="cargo.uuid", read_only=True)
    cargo_origin = serializers.CharField(source="cargo.origin_city", read_only=True)
    cargo_destination = serializers.CharField(source="cargo.destination_city", read_only=True)
    cargo_customer_id = serializers.IntegerField(source="cargo.customer_id", read_only=True)

    class Meta:
        model = Offer
        fields = (
            "id",
            "cargo",
            "cargo_uuid",
            "cargo_origin",
            "cargo_destination",
            "cargo_customer_id",
            "price_value",
            "price_currency",
            "message",
            "accepted_by_customer",
            "accepted_by_carrier",
            "is_active",
            "created_at",
        )
        read_only_fields = fields


class OfferDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = "__all__"
        read_only_fields = (
            "carrier",
            "initiator",
            "accepted_by_customer",
            "accepted_by_carrier",
            "is_active",
            "created_at",
            "updated_at",
        )


class OfferCounterSerializer(serializers.Serializer):
    """
    Контр-предложение (любой стороной).
    """

    price_value = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    price_currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    message = serializers.CharField(required=False, allow_blank=True)


class OfferAcceptResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    accepted_by_customer = serializers.BooleanField()
    accepted_by_carrier = serializers.BooleanField()


class OfferRejectResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
