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
    Driver = getattr(Order, "DriverStatus", None)
    if Driver is not None and hasattr(Driver, "choices"):
        return Driver.choices
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
        read_only_fields = ("id", "uploaded_by", "created_at")

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_name(self, obj):
        try:
            return os.path.basename(obj.file.name)
        except Exception:
            return None

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_file_size(self, obj):
        try:
            return int(obj.file.size)
        except Exception:
            return None


class OrderListSerializer(serializers.ModelSerializer):
    price_per_km = serializers.FloatField(read_only=True)
    cargo_id = serializers.IntegerField(read_only=True)

    status = serializers.ChoiceField(choices=_order_status_choices())
    driver_status = serializers.ChoiceField(choices=_driver_status_choices(), read_only=True)
    currency = serializers.ChoiceField(choices=_currency_choices())
    currency_display = serializers.CharField(source="get_currency_display", read_only=True)

    customer_name = serializers.SerializerMethodField()
    carrier_name = serializers.SerializerMethodField()
    logistic_name = serializers.SerializerMethodField()

    origin_city = serializers.CharField(source="cargo.origin_city", read_only=True)
    destination_city = serializers.CharField(source="cargo.destination_city", read_only=True)
    load_date = serializers.DateField(source="cargo.load_date", read_only=True)
    delivery_date = serializers.DateField(source="cargo.delivery_date", read_only=True)

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
            "customer",
            "carrier",
            "driver_status",
            "cargo_id",
            "price_per_km",
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
        return self._user_display_name(obj.customer)

    def get_carrier_name(self, obj):
        return self._user_display_name(obj.carrier)

    def get_logistic_name(self, obj):
        u = obj.created_by
        if u and (getattr(u, "is_logistic", False) or getattr(u, "role", "") == "LOGISTIC"):
            return self._user_display_name(u)
        return ""

    @extend_schema_field(serializers.IntegerField())
    def get_documents_count(self, obj):
        try:
            return obj.documents.count()
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
        return getattr(u, "full_name", None) or getattr(u, "name", None) or u.username
