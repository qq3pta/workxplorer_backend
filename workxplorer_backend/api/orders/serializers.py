import os
from collections.abc import Iterable

from api.loads.choices import Currency
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Order, OrderDocument


def _field_choices(model, field_name: str) -> Iterable[tuple[str, str]]:
    """Возвращает choices у поля модели."""
    return model._meta.get_field(field_name).choices


def _order_status_choices() -> Iterable[tuple[str, str]]:
    Status = getattr(Order, "Status", None)
    if Status is not None and hasattr(Status, "choices"):
        return Status.choices
    return _field_choices(Order, "status")


def _currency_choices() -> Iterable[tuple[str, str]]:
    if hasattr(Currency, "choices"):
        return Currency.choices
    return _field_choices(Order, "currency")


class OrderDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)
    file_name = serializers.SerializerMethodField(read_only=True)
    file_size = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OrderDocument
        fields = (
            "id",
            "title",
            "file",
            "file_name",
            "file_size",
            "uploaded_by",
            "created_at",
        )

    @extend_schema_field(serializers.CharField(allow_null=True, allow_blank=True))
    def get_file_name(self, obj) -> str | None:
        try:
            name = getattr(obj.file, "name", None)
            return os.path.basename(name) if name else None
        except Exception:
            return None

    @extend_schema_field(serializers.IntegerField(allow_null=True, min_value=0))
    def get_file_size(self, obj) -> int | None:
        try:
            size = getattr(obj.file, "size", None)
            return int(size) if size is not None else None
        except Exception:
            return None


class OrderListSerializer(serializers.ModelSerializer):
    price_per_km = serializers.FloatField(read_only=True)
    cargo_id = serializers.IntegerField(read_only=True)
    status = serializers.ChoiceField(choices=_order_status_choices())
    currency = serializers.ChoiceField(choices=_currency_choices())

    class Meta:
        model = Order
        fields = (
            "id",
            "cargo",
            "cargo_id",
            "customer",
            "carrier",
            "status",
            "currency",
            "price_total",
            "route_distance_km",
            "price_per_km",
            "created_at",
        )
        read_only_fields = ("id", "created_at", "price_per_km")


class OrderDetailSerializer(OrderListSerializer):
    documents = OrderDocumentSerializer(many=True, read_only=True)

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + ("documents",)


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(choices=_order_status_choices())

    class Meta:
        model = Order
        fields = ("status",)
