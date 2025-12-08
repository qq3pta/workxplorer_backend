from rest_framework import serializers
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = (
            "status",
            "confirmed_by_customer",
            "confirmed_by_carrier",
            "created_at",
            "completed_at",
        )


class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["order", "amount", "currency", "method"]
