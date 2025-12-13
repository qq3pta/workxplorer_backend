from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.loads.choices import Currency, ModerationStatus
from api.loads.models import Cargo, CargoStatus

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

        if getattr(cargo, "is_hidden", False):
            raise serializers.ValidationError({"cargo": "Заявка скрыта."})
        if cargo.moderation_status != ModerationStatus.APPROVED:
            raise serializers.ValidationError({"cargo": "Заявка не прошла модерацию."})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"cargo": "Заявка уже не активна."})

        if Offer.objects.filter(cargo=cargo, carrier=user, is_active=True).exists():
            raise serializers.ValidationError(
                {"cargo": "У вас уже есть активный оффер на эту заявку."}
            )

        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        cargo = validated_data["cargo"]

        logistic_user = None
        if cargo.created_by and getattr(cargo.created_by, "role", None) == "LOGISTIC":
            logistic_user = cargo.created_by

        deal_type = Offer.resolve_deal_type(
            initiator_user=user,
            carrier=user,
            logistic=logistic_user,
        )

        offer = Offer.objects.create(
            carrier=user,
            initiator=Offer.Initiator.CARRIER,
            logistic=logistic_user,
            deal_type=deal_type,
            **validated_data,
        )

        offer.send_create_notifications()
        return offer


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

        if cargo.customer_id != user.id and not getattr(user, "is_logistic", False):
            raise serializers.ValidationError({"cargo": "Можно приглашать только на свою заявку."})

        if carrier.id == user.id:
            raise serializers.ValidationError({"carrier_id": "Нельзя приглашать самого себя."})

        if getattr(cargo, "is_hidden", False):
            raise serializers.ValidationError({"cargo": "Заявка скрыта."})
        if cargo.moderation_status != ModerationStatus.APPROVED:
            raise serializers.ValidationError({"cargo": "Заявка не прошла модерацию."})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"cargo": "Заявка не активна."})

        if Offer.objects.filter(cargo=cargo, carrier=carrier, is_active=True).exists():
            raise serializers.ValidationError(
                {"carrier_id": "Этому перевозчику уже отправлено активное предложение."}
            )
        return attrs

    def create(self, validated_data):
        cargo = validated_data["cargo"]
        carrier = validated_data["carrier"]

        logistic_user = None
        if cargo.created_by and getattr(cargo.created_by, "role", None) == "LOGISTIC":
            logistic_user = cargo.created_by

        # --- Создаём оффер корректно ---
        initiator_user = self.context["request"].user

        deal_type = Offer.resolve_deal_type(
            initiator_user=initiator_user,
            carrier=carrier,
            logistic=logistic_user,
        )

        offer = Offer.objects.create(
            cargo=cargo,
            carrier=carrier,
            price_value=validated_data.get("price_value"),
            price_currency=validated_data.get("price_currency", Currency.UZS),
            message=validated_data.get("message", ""),
            initiator=Offer.Initiator.CUSTOMER,
            logistic=logistic_user,
            deal_type=deal_type,
        )

        offer.send_invite_notifications()
        return offer


class OfferShortSerializer(serializers.ModelSerializer):
    """
    Короткая карточка оффера для списков
    (экраны «Мои предложения → Я предложил / Предложили мне»).
    """

    cargo_uuid = serializers.UUIDField(source="cargo.uuid", read_only=True)
    cargo_title = serializers.CharField(source="cargo.product", read_only=True)

    customer_company = serializers.SerializerMethodField()
    customer_full_name = serializers.SerializerMethodField()
    customer_id = serializers.IntegerField(source="cargo.customer.id", read_only=True)

    origin_city = serializers.CharField(source="cargo.origin_city", read_only=True)
    origin_country = serializers.CharField(source="cargo.origin_country", read_only=True)
    load_date = serializers.DateField(source="cargo.load_date", read_only=True)

    destination_city = serializers.CharField(source="cargo.destination_city", read_only=True)
    destination_country = serializers.CharField(source="cargo.destination_country", read_only=True)
    delivery_date = serializers.DateField(
        source="cargo.delivery_date", read_only=True, allow_null=True
    )

    transport_type = serializers.CharField(source="cargo.transport_type", read_only=True)
    transport_type_display = serializers.SerializerMethodField()
    weight_t = serializers.SerializerMethodField()

    carrier_company = serializers.SerializerMethodField()
    carrier_full_name = serializers.SerializerMethodField()
    carrier_id = serializers.IntegerField(read_only=True)
    carrier_rating = serializers.FloatField(read_only=True)
    invite_token = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    route_km = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    source_status = serializers.SerializerMethodField()
    price_per_km = serializers.SerializerMethodField()

    status_display = serializers.SerializerMethodField()
    is_handshake = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = (
            "id",
            "cargo",
            "cargo_uuid",
            "cargo_title",
            "customer_company",
            "customer_id",
            "customer_full_name",
            "origin_city",
            "origin_country",
            "load_date",
            "destination_city",
            "destination_country",
            "delivery_date",
            "transport_type",
            "transport_type_display",
            "weight_t",
            "carrier_company",
            "carrier_full_name",
            "carrier_id",
            "carrier_rating",
            "phone",
            "email",
            "route_km",
            "price_value",
            "price_currency",
            "payment_method",
            "price_per_km",
            "accepted_by_customer",
            "accepted_by_carrier",
            "accepted_by_logistic",
            "is_active",
            "status_display",
            "is_handshake",
            "source_status",
            "message",
            "created_at",
            "invite_token",
        )
        read_only_fields = fields

    # ----- helpers -----

    def _get_user_full_name(self, user) -> str:
        """Вспомогательный метод для получения полного имени (ФИО)."""
        if not user:
            return ""
        return user.get_full_name() or getattr(user, "name", None) or ""

    def get_customer_company(self, obj: Offer) -> str:
        """Название компании заказчика (строго только компания)."""
        u = obj.cargo.customer
        if not u:
            return ""
        return getattr(u, "company_name", "")

    def get_customer_full_name(self, obj: Offer) -> str:
        """Полное имя заказчика (строго ФИО)."""
        return self._get_user_full_name(obj.cargo.customer)

    def get_carrier_company(self, obj: Offer) -> str:
        """Название компании перевозчика (строго только компания)."""
        u = obj.carrier
        if not u:
            return ""
        return getattr(u, "company_name", "")

    def get_carrier_full_name(self, obj: Offer) -> str:
        """Полное имя перевозчика (строго ФИО)."""
        return self._get_user_full_name(obj.carrier)

    def get_transport_type_display(self, obj: Offer) -> str:
        """
        Для колонки «Тип» в макете (Т, Р, М, С, П...).
        Если в Cargo есть choices, берём label и первую букву.
        """
        cargo = obj.cargo
        if hasattr(cargo, "get_transport_type_display"):
            label = cargo.get_transport_type_display()
            return label[:1] if label else ""
        return (cargo.transport_type or "")[:1]

    def get_weight_t(self, obj: Offer) -> float | None:
        """
        Вес в тоннах для колонки «Вес (т)».
        """
        cargo = obj.cargo
        if cargo.weight_kg is None:
            return None
        try:
            return round(float(cargo.weight_kg) / 1000.0, 1)
        except Exception:
            return None

    def get_phone(self, obj: Offer) -> str:
        """
        Телефон перевозчика (вместо contact_value).
        """
        u = obj.carrier
        if not u:
            return ""
        phone = getattr(u, "phone", None) or getattr(u, "phone_number", None)
        return phone or ""

    def get_email(self, obj: Offer) -> str:
        """
        Email перевозчика (вместо contact_value).
        """
        u = obj.carrier
        if not u:
            return ""
        return getattr(u, "email", "") or ""

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_route_km(self, obj):
        cargo = obj.cargo

        val = getattr(cargo, "route_km", None)
        if val is not None:
            try:
                return round(float(val), 1)
            except Exception:
                pass

        val = getattr(cargo, "route_km_cached", None)
        if val is not None:
            try:
                return round(float(val), 1)
            except Exception:
                pass

        val = getattr(cargo, "path_km", None)
        if val is not None:
            try:
                return round(float(val), 1)
            except Exception:
                pass

        return None

    @extend_schema_field(str)
    def get_payment_method(self, obj: Offer) -> str:
        """
        Способ оплаты: «Картой» / «Наличными».

        Ожидается, что в модели Offer есть поле payment_method или payment_type
        с кодами вида: CARD / CASH / BY_CARD / BY_CASH.
        Если поля нет — вернётся пустая строка (getattr с default).
        """
        code = getattr(obj, "payment_method", None) or getattr(obj, "payment_type", None)
        if not code:
            return ""
        code = str(code).upper()
        if code in ("CARD", "BY_CARD"):
            return "Картой"
        if code in ("CASH", "BY_CASH"):
            return "Наличными"
        return ""

    @extend_schema_field(str)
    def get_source_status(self, obj: Offer) -> str:
        """
        Статусы:
        - «Предложение от заказчика» (инициатор CUSTOMER)
        - «Предложение от посредника» (инициатор CARRIER)
        """
        init = getattr(obj, "initiator", None)
        try:
            from .models import Offer as OfferModel

            if init == OfferModel.Initiator.CUSTOMER:
                return "Предложение от заказчика"
            if init == OfferModel.Initiator.CARRIER:
                return "Предложение от посредника"
        except Exception:
            pass

        if not init:
            return ""
        code = str(init).upper()
        if code in ("CUSTOMER", "FROM_CUSTOMER"):
            return "Предложение от заказчика"
        if code in ("CARRIER", "BROKER", "INTERMEDIARY", "FROM_BROKER"):
            return "Предложение от посредника"
        return ""

    def get_is_handshake(self, obj: Offer) -> bool:
        """
        Флаг, что оффер принят обеими сторонами
        (для зелёной галочки / завершённой сделки).
        """
        return bool(obj.accepted_by_customer and obj.accepted_by_carrier and obj.is_active)

    def get_status_display(self, obj: Offer) -> str:
        """
        Человекочитаемый статус под макет.
        Можно потом подправить формулировки под точные ТЗ.
        """
        if not obj.is_active:
            return "Отменено"

        if obj.accepted_by_customer and obj.accepted_by_carrier:
            return "Ответ получен"

        if obj.accepted_by_carrier and not obj.accepted_by_customer:
            return "Ожидает ответа"

        if obj.accepted_by_customer and not obj.accepted_by_carrier:
            return "Ожидает ответа"

        return "Ожидает ответа"

    def get_price_per_km(self, obj) -> Decimal | None:
        """
        Рассчитывает цену за километр, используя цену оффера и расстояние груза.
        """
        price = obj.price_value
        dist = self.get_route_km(obj)

        if not price or not dist or float(dist) == 0:
            return None

        try:
            from decimal import ROUND_HALF_UP

            return (Decimal(str(price)) / Decimal(str(dist))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except Exception:
            return None

    def get_invite_token(self, obj):
        from api.orders.models import Order

        try:
            order = Order.objects.get(cargo=obj.cargo)
            return str(order.invite_token) if order.invite_token else None
        except Order.DoesNotExist:
            return None


class OfferDetailSerializer(OfferShortSerializer):
    """
    Детальная карточка оффера. Наследует все поля из OfferShortSerializer
    и добавляет служебные поля вроде `updated_at`.
    """

    class Meta(OfferShortSerializer.Meta):
        fields = OfferShortSerializer.Meta.fields + ("updated_at",)
        read_only_fields = fields


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
    accepted_by_logistic = serializers.BooleanField()
    order_id = serializers.IntegerField(allow_null=True, required=False)


class OfferRejectResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
