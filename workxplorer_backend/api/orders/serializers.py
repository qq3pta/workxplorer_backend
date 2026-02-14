import os
from collections.abc import Iterable

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.payments.serializers import PaymentSerializer
from api.loads.choices import Currency
from api.payments.models import PaymentMethod

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
    rated = serializers.SerializerMethodField()

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
            "rated",
            "created_at",
            "share_token",
        )
        read_only_fields = (
            "id",
            "created_at",
            "customer",
            "carrier",
            "driver_status",
            "cargo_id",
            "price_per_km",
            "rated",
        )

    def get_rated(self, obj):
        """
        rated: кто → кому → score + rating_id
        """
        result = {
            "by_customer": {},
            "by_carrier": {},
            "by_logistic": {},
        }

        ratings = getattr(obj, "ratings", None)
        if not ratings:
            return result

        role_map = {
            "CUSTOMER": "by_customer",
            "CARRIER": "by_carrier",
            "LOGISTIC": "by_logistic",
        }

        for r in ratings.all():
            if not r.rated_by or not r.rated_user:
                continue

            from_role = role_map.get(getattr(r.rated_by, "role", None))
            to_role = getattr(r.rated_user, "role", "").lower()

            if not from_role or not to_role:
                continue

            result[from_role][f"{to_role}_value"] = r.score
            result[from_role][f"{to_role}_rating_id"] = r.id

        return result

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
        request = self.context.get("request")
        request_user = request.user if request else None

        def user_info(u):
            if not u:
                return None

            request = self.context.get("request")
            request_user = request.user if request else None

            hidden = False
            hidden_by = None

            # =========================
            # СКРЫТИЕ ЗАКАЗЧИКА
            # =========================
            if u.id == obj.customer_id:
                if obj.customer_hide_contacts:
                    hidden = True

                if obj.logistic_hide_contacts:
                    hidden = True
                    hidden_by = "logistic"

            # =========================
            # КТО ЧТО ВИДИТ
            # =========================
            is_customer = request_user and request_user.id == obj.customer_id
            is_carrier = request_user and request_user.id == obj.carrier_id
            is_logistic = request_user and request_user.id == obj.logistic_id

            if is_customer and hidden_by == "logistic":
                hidden = False
                hidden_by = None
                if not hidden:
                    hidden_by = None

            hide_contacts = is_carrier and hidden and not is_logistic

            data = {
                "id": u.id,
                "name": None if hide_contacts else self._get_user_full_name(u),
                "company": self._get_user_company(u),
                "login": u.username,
                "phone": None if hide_contacts else getattr(u, "phone", None),
                "email": None if hide_contacts else getattr(u, "email", None),
                "role": getattr(u, "role", None),
                "hidden": hidden if not is_customer else False,
            }

            if hidden_by and is_logistic:
                data["hidden_by"] = hidden_by

            return data

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
    payment = serializers.SerializerMethodField()
    driver_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    logistic_margin = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + (
            "loading_datetime",
            "unloading_datetime",
            "documents",
            "payment",
            "driver_price",
            "logistic_margin",
        )

    def get_payment(self, obj):
        payment = obj.payments.first()
        if not payment:
            return None
        return PaymentSerializer(payment).data

    def get_logistic_margin(self, obj):
        if obj.driver_price:
            return float(obj.price_total) - float(obj.driver_price)
        return None


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

    driver_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=True,
        min_value=0,
        help_text="Сумма, которую получит водитель",
    )

    driver_currency = serializers.ChoiceField(
        choices=Currency.choices,
        required=True,
        help_text="Валюта выплаты водителю",
    )

    driver_payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        required=True,
        help_text="Способ оплаты водителю",
    )


class InvitePreviewSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()

    origin_city = serializers.CharField(allow_null=True)
    destination_city = serializers.CharField(allow_null=True)

    load_date = serializers.DateField(allow_null=True)
    delivery_date = serializers.DateField(allow_null=True)

    route_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)

    weight_kg = serializers.IntegerField(allow_null=True)
    transport_type = serializers.CharField(allow_null=True)

    inviter = serializers.DictField(allow_null=True)

    driver_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        allow_null=True,
    )
    driver_currency = serializers.CharField(allow_null=True)
    driver_payment_method = serializers.CharField(allow_null=True)
