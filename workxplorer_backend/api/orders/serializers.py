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

    customer_company = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    customer_id = serializers.IntegerField(source="customer.id", read_only=True)

    carrier_company = serializers.SerializerMethodField()
    carrier_name = serializers.SerializerMethodField()
    carrier_id = serializers.IntegerField(source="carrier.id", read_only=True)

    logistic_company = serializers.SerializerMethodField()
    logistic_name = serializers.SerializerMethodField()
    logistic_id = serializers.IntegerField(source="logistic.id", read_only=True)

    roles = serializers.SerializerMethodField()

    origin_city = serializers.CharField(source="cargo.origin_city", read_only=True)
    destination_city = serializers.CharField(source="cargo.destination_city", read_only=True)

    origin_address = serializers.CharField(source="cargo.origin_address", read_only=True)
    destination_address = serializers.CharField(source="cargo.destination_address", read_only=True)

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
            "customer_id",
            "customer_company",
            "customer_name",
            "carrier",
            "carrier_id",
            "carrier_company",
            "carrier_name",
            "logistic_id",
            "logistic_company",
            "logistic_name",
            "roles",
            "status",
            "driver_status",
            "currency",
            "currency_display",
            "price_total",
            "route_distance_km",
            "price_per_km",
            "origin_city",
            "origin_address",
            "load_date",
            "destination_city",
            "destination_address",
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

    # --------------------------
    # HELPERS
    # --------------------------

    def _get_user_company(self, u):
        return getattr(u, "company_name", "") if u else ""

    def _get_user_full_name(self, u):
        if not u:
            return ""
        return u.get_full_name() or getattr(u, "name", "") or getattr(u, "username", "")

    # --------------------------
    # GETTERS
    # --------------------------

    def get_customer_company(self, obj):
        return self._get_user_company(obj.customer)

    def get_customer_name(self, obj):
        return self._get_user_full_name(obj.customer)

    def get_carrier_company(self, obj):
        return self._get_user_company(obj.carrier)

    def get_carrier_name(self, obj):
        return self._get_user_full_name(obj.carrier)

    def get_logistic_company(self, obj):
        return self._get_user_company(obj.logistic)

    def get_logistic_name(self, obj):
        return self._get_user_full_name(obj.logistic)

    def get_roles(self, obj):
        def user_info(u):
            if not u:
                return None
            return {
                "id": u.id,
                "name": self._get_user_full_name(u),
                "company": self._get_user_company(u),
                "login": u.username,
                "phone": getattr(u, "phone", None),
                "role": getattr(u, "role", None),
            }

        # CUSTOMER всегда выводим как есть
        customer = user_info(obj.customer)

        # ---------------------------
        # LOGISTIC — только если он НЕ равен заказчику
        # ---------------------------

        logistic_user = None

        # Если в заказе указан логист, но это НЕ заказчик
        if obj.logistic_id and obj.logistic_id != obj.customer_id:
            logistic_user = obj.logistic

        # Если created_by является ЛОГИСТОМ, но это НЕ заказчик
        elif (
            obj.created_by_id
            and obj.created_by_id != obj.customer_id
            and getattr(obj.created_by, "role", "") == "LOGISTIC"
        ):
            logistic_user = obj.created_by

        logistic = user_info(logistic_user)

        # Перевозчик
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
