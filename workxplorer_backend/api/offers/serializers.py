from rest_framework import serializers
from django.utils import timezone
from django.contrib.auth import get_user_model
from ..loads.models import Cargo, CargoStatus
from ..loads.choices import Currency
from .models import Offer, OfferStatus, OfferEvent, OfferEventType

User = get_user_model()

class OfferCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = ("amount_value","amount_currency")

    def validate(self, attrs):
        request = self.context["request"]
        cargo: Cargo = self.context["cargo"]
        if cargo.customer_id == request.user.id:
            raise serializers.ValidationError({"detail": "Нельзя предлагать на свою заявку"})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"detail": "Заявка недоступна"})
        return attrs

    def create(self, validated):
        cargo: Cargo = self.context["cargo"]
        offer = Offer.objects.create(
            cargo=cargo,
            carrier=self.context["request"].user,
            amount_value=validated.get("amount_value"),
            amount_currency=validated.get("amount_currency") or Currency.UZS,
        )
        OfferEvent.objects.create(
            offer=offer,
            actor=self.context["request"].user,
            type=OfferEventType.OFFERED,
            amount_value=offer.amount_value,
            amount_currency=offer.amount_currency,
        )
        return offer

class OfferListItemSerializer(serializers.ModelSerializer):
    carrier_username = serializers.CharField(source="carrier.username", read_only=True)
    class Meta:
        model = Offer
        fields = ("id","carrier","carrier_username","amount_value","amount_currency","status","created_at","updated_at")

class OfferCounterSerializer(serializers.Serializer):
    amount_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    amount_currency = serializers.ChoiceField(choices=Currency.choices)

class OfferTargetSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="логин или email или телефон или название компании")
    expires_at = serializers.DateTimeField(required=False)

class OfferAcceptSerializer(serializers.Serializer):
    pass