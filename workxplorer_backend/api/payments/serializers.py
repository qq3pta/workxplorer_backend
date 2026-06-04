from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source="order.id", read_only=True)
    price_total = serializers.DecimalField(
        source="order.price_total",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    order_currency = serializers.CharField(source="order.currency", read_only=True)
    payment_method = serializers.CharField(source="order.payment_method", read_only=True)
    driver_price = serializers.DecimalField(
        source="order.driver_price",
        max_digits=14,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    driver_currency = serializers.CharField(source="order.driver_currency", read_only=True)
    driver_payment_method = serializers.CharField(
        source="order.driver_payment_method",
        read_only=True,
    )
    logistic_margin = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = (
            "id",
            "order",
            "order_id",
            "amount",
            "currency",
            "method",
            "status",
            "confirmed_by_customer",
            "confirmed_by_logistic",
            "confirmed_by_carrier",
            "external_transaction_id",
            "created_at",
            "completed_at",
            "price_total",
            "order_currency",
            "payment_method",
            "driver_price",
            "driver_currency",
            "driver_payment_method",
            "logistic_margin",
        )
        read_only_fields = (
            "status",
            "confirmed_by_customer",
            "confirmed_by_logistic",
            "confirmed_by_carrier",
            "created_at",
            "completed_at",
            "price_total",
            "order_currency",
            "payment_method",
            "driver_price",
            "driver_currency",
            "driver_payment_method",
            "logistic_margin",
        )

    def get_logistic_margin(self, obj):
        order = obj.order
        if order and order.driver_price is not None:
            return float(order.price_total) - float(order.driver_price)
        return None


class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["order", "amount", "currency", "method"]
