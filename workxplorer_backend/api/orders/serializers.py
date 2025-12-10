import os
from collections.abc import Iterable

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.loads.choices import Currency
from .models import Order, OrderDocument, OrderStatusHistory


def _field_choices(model, field_name: str) -> Iterable[tuple[str, str]]:
    return model._meta.get_field(field_name).choices


def _order_status_choices():
    Status = getattr(Order, "OrderStatus", None)
    if Status and hasattr(Status, "choices"):
        return Status.choices
    return _field_choices(Order, "status")


def _driver_status_choices():
    Driver = getattr(Order, "DriverStatus", None)
    if Driver and hasattr(Driver, "choices"):
        return Driver.choices
    return _field_choices(Order, "driver_status")


def _currency_choices():
    if hasattr(Currency, "choices"):
        return Currency.choices
    return _field_choices(Order, "currency")


# --------------------------
# DOCUMENT SERIALIZER
# --------------------------


class OrderDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)
    file_name = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    category_display = serializers.CharField(source="get_category_display", read_only=True)

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
        return os.path.basename(obj.file.name) if obj.file else None

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_file_size(self, obj):
        return int(obj.file.size) if obj.file else None


# --------------------------
# ORDER LIST / DETAIL SERIALIZER
# --------------------------


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

    roles = serializers.SerializerMethodField()  # <---- Новый корректный блок

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
            # users
            "customer",
            "customer_name",
            "carrier",
            "carrier_name",
            "logistic_name",
            "roles",
            # status
            "status",
            "driver_status",
            # pricing
            "currency",
            "currency_display",
            "price_total",
            "route_distance_km",
            "price_per_km",
            # location
            "origin_city",
            "load_date",
            "destination_city",
            "delivery_date",
            # misc
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

    # --------------------------
    # NAME HELPERS
    # --------------------------

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
        if obj.logistic:
            return self._user_display_name(obj.logistic)
        return ""

    # --------------------------
    # ROLES BLOCK FOR FRONT
    # --------------------------

    def get_roles(self, obj):
        def user_info(u):
            if not u:
                return None
            return {
                "id": u.id,
                "name": getattr(u, "company_name", None) or getattr(u, "name", None) or u.username,
                "login": u.username,
                "phone": getattr(u, "phone", None),
                "company": getattr(u, "company_name", None) or getattr(u, "company", None),
                "role": getattr(u, "role", None),
            }

        # CUSTOMER — всегда
        customer = user_info(obj.customer)

        # LOGISTIC — только если created_by.role == LOGISTIC
        logistic_user = obj.logistic or (
            obj.created_by if getattr(obj.created_by, "role", "") == "LOGISTIC" else None
        )
        logistic = user_info(logistic_user)

        # CARRIER — только когда назначен
        carrier = user_info(obj.carrier)

        return {
            "customer": customer,
            "logistic": logistic,
            "carrier": carrier,
        }

    # --------------------------
    # DOCUMENTS COUNT
    # --------------------------

    @extend_schema_field(serializers.IntegerField())
    def get_documents_count(self, obj):
        return obj.documents.count()


# --------------------------
# ORDER DETAIL
# --------------------------


class OrderDetailSerializer(OrderListSerializer):
    documents = OrderDocumentSerializer(many=True, read_only=True)

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + (
            "loading_datetime",
            "unloading_datetime",
            "documents",
        )


# --------------------------
# DRIVER STATUS UPDATE
# --------------------------


class OrderDriverStatusUpdateSerializer(serializers.ModelSerializer):
    driver_status = serializers.ChoiceField(choices=_driver_status_choices())

    class Meta:
        model = Order
        fields = ("driver_status",)


# --------------------------
# STATUS HISTORY
# --------------------------


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


# --------------------------
# INVITE SERIALIZER
# --------------------------


class InviteByIdSerializer(serializers.Serializer):
    driver_id = serializers.IntegerField(required=True)
