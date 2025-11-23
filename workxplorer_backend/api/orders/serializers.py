import os
from collections.abc import Iterable

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.loads.choices import Currency

from .models import Order, OrderDocument, OrderStatusHistory


def _field_choices(model, field_name: str) -> Iterable[tuple[str, str]]:
    """Возвращает choices у поля модели."""
    return model._meta.get_field(field_name).choices


def _order_status_choices() -> Iterable[tuple[str, str]]:
    Status = getattr(Order, "OrderStatus", None)
    if Status is not None and hasattr(Status, "choices"):
        return Status.choices
    return _field_choices(Order, "status")


def _driver_status_choices() -> Iterable[tuple[str, str]]:
    DriverStatus = getattr(Order, "DriverStatus", None)
    if DriverStatus is not None and hasattr(DriverStatus, "choices"):
        return DriverStatus.choices
    return _field_choices(Order, "driver_status")


def _currency_choices() -> Iterable[tuple[str, str]]:
    if hasattr(Currency, "choices"):
        return Currency.choices
    return _field_choices(Order, "currency")


class OrderDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)
    file_name = serializers.SerializerMethodField(read_only=True)
    file_size = serializers.SerializerMethodField(read_only=True)

    category = serializers.ChoiceField(
        choices=OrderDocument.Category.choices,
        required=False,
        default=OrderDocument.Category.OTHER,
    )

    category_display = serializers.CharField(
        source="get_category_display",
        read_only=True,
    )

    class Meta:
        model = OrderDocument
        fields = (
            "id",
            "title",
            "category",
            "category_display",
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
            return 0


class OrderListSerializer(serializers.ModelSerializer):
    # агрегаты / вычисляемые поля
    price_per_km = serializers.FloatField(read_only=True)
    cargo_id = serializers.IntegerField(read_only=True)

    status = serializers.ChoiceField(choices=_order_status_choices())
    driver_status = serializers.ChoiceField(choices=_driver_status_choices(), read_only=True)
    currency = serializers.ChoiceField(choices=_currency_choices())
    currency_display = serializers.CharField(
        source="get_currency_display",
        read_only=True,
    )

    customer_name = serializers.SerializerMethodField()
    carrier_name = serializers.SerializerMethodField()
    logistic_name = serializers.SerializerMethodField()

    origin_city = serializers.CharField(source="cargo.origin_city", read_only=True)
    destination_city = serializers.CharField(source="cargo.destination_city", read_only=True)
    load_date = serializers.DateField(source="cargo.load_date", read_only=True)
    delivery_date = serializers.DateField(
        source="cargo.delivery_date",
        read_only=True,
        allow_null=True,
    )

    documents_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "id",
            "cargo",
            "cargo_id",
            "customer",
            "customer_name",
            "carrier",
            "carrier_name",
            "logistic_name",
            "status",
            "driver_status",
            "currency",
            "currency_display",
            "price_total",
            "route_distance_km",
            "price_per_km",
            "origin_city",
            "load_date",
            "destination_city",
            "delivery_date",
            "documents_count",
            "created_at",
        )
        read_only_fields = (
            "id",
            "created_at",
            "price_per_km",
            "cargo_id",
            "customer",
            "carrier",
            "driver_status",
        )

    def _user_display_name(self, u):
        if not u:
            return ""
        return (
            getattr(u, "company_name", None)
            or getattr(u, "company", None)
            or getattr(u, "name", None)
            or getattr(u, "username", "")
        )

    def get_customer_name(self, obj):
        return self._user_display_name(getattr(obj, "customer", None))

    def get_carrier_name(self, obj):
        return self._user_display_name(getattr(obj, "carrier", None))

    def get_logistic_name(self, obj):
        u = getattr(obj, "created_by", None)
        if not u:
            return ""
        if getattr(u, "is_logistic", False) or getattr(u, "role", None) == "LOGISTIC":
            return self._user_display_name(u)
        return ""

    @extend_schema_field(serializers.IntegerField(allow_null=False, min_value=0))
    def get_documents_count(self, obj) -> int:
        rel = getattr(obj, "documents", None)
        try:
            return rel.count() if rel is not None else 0
        except Exception:
            return 0


class OrderDetailSerializer(OrderListSerializer):
    documents = OrderDocumentSerializer(many=True, read_only=True)

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + (
            "loading_datetime",
            "unloading_datetime",
            "documents",
        )


class OrderDriverStatusUpdateSerializer(serializers.ModelSerializer):
    driver_status = serializers.ChoiceField(choices=_driver_status_choices())

    class Meta:
        model = Order
        fields = ("driver_status",)


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    old_status_label = serializers.CharField(source="get_old_status_display", read_only=True)
    new_status_label = serializers.CharField(source="get_new_status_display", read_only=True)

    class Meta:
        model = OrderStatusHistory
        fields = (
            "id",
            "user_name",
            "old_status",
            "old_status_label",
            "new_status",
            "new_status_label",
            "created_at",
        )

    def get_user_name(self, obj):
        u = obj.user
        if not u:
            return ""
        return (
            getattr(u, "full_name", None) or getattr(u, "name", None) or getattr(u, "username", "")
        )
