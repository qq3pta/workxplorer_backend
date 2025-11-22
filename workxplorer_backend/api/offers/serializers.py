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

        # Груз должен быть опубликован и доступен
        if getattr(cargo, "is_hidden", False):
            raise serializers.ValidationError({"cargo": "Заявка скрыта."})
        if cargo.moderation_status != ModerationStatus.APPROVED:
            raise serializers.ValidationError({"cargo": "Заявка не прошла модерацию."})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"cargo": "Заявка уже не активна."})

        # Только один активный оффер на пару cargo-carrier
        if Offer.objects.filter(cargo=cargo, carrier=user, is_active=True).exists():
            raise serializers.ValidationError(
                {"cargo": "У вас уже есть активный оффер на эту заявку."}
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> Offer:
        user = self.context["request"].user
        return Offer.objects.create(
            carrier=user,
            initiator=Offer.Initiator.CARRIER,
            **validated_data,
        )


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

        # Права: только владелец груза (или логист, если у вас такая роль есть)
        if cargo.customer_id != user.id and not getattr(user, "is_logistic", False):
            raise serializers.ValidationError({"cargo": "Можно приглашать только на свою заявку."})

        if carrier.id == user.id:
            raise serializers.ValidationError({"carrier_id": "Нельзя приглашать самого себя."})

        # Только активные и одобренные заявки
        if getattr(cargo, "is_hidden", False):
            raise serializers.ValidationError({"cargo": "Заявка скрыта."})
        if cargo.moderation_status != ModerationStatus.APPROVED:
            raise serializers.ValidationError({"cargo": "Заявка не прошла модерацию."})
        if cargo.status != CargoStatus.POSTED:
            raise serializers.ValidationError({"cargo": "Заявка не активна."})

        # Один активный оффер на пару cargo-carrier
        if Offer.objects.filter(cargo=cargo, carrier=carrier, is_active=True).exists():
            raise serializers.ValidationError(
                {"carrier_id": "Этому перевозчику уже отправлено активное предложение."}
            )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Offer:
        return Offer.objects.create(
            initiator=Offer.Initiator.CUSTOMER,
            **validated_data,
        )


class OfferShortSerializer(serializers.ModelSerializer):
    """
    Короткая карточка оффера для списков
    (экраны «Мои предложения → Я предложил / Предложили мне»).
    """

    # --- Данные по грузу (для колонок Откуда/Куда/Дата/Тип/Вес) ---
    cargo_uuid = serializers.UUIDField(source="cargo.uuid", read_only=True)

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

    # --- Перевозчик / рейтинг / контакты ---
    carrier_name = serializers.SerializerMethodField()
    carrier_rating = serializers.FloatField(read_only=True)
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()

    # --- Оплата и источник предложения ---
    payment_method = serializers.SerializerMethodField()
    source_status = serializers.SerializerMethodField()

    # --- Статус для цветных “чипсов” ---
    status_display = serializers.SerializerMethodField()
    is_handshake = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = (
            "id",
            "cargo",
            "cargo_uuid",
            # груз
            "origin_city",
            "origin_country",
            "load_date",
            "destination_city",
            "destination_country",
            "delivery_date",
            "transport_type",
            "transport_type_display",
            "weight_t",
            # перевозчик
            "carrier_name",
            "carrier_rating",
            "phone",
            "email",
            # деньги
            "price_value",
            "price_currency",
            "payment_method",
            # статус оффера
            "accepted_by_customer",
            "accepted_by_carrier",
            "is_active",
            "status_display",
            "is_handshake",
            "source_status",
            # доп. инфо
            "message",
            "created_at",
        )
        read_only_fields = fields

    # ----- helpers -----

    def get_transport_type_display(self, obj: Offer) -> str:
        """
        Для колонки «Тип» в макете (Т, Р, М, С, П...).
        Если в Cargo есть choices, берём label и первую букву.
        """
        cargo = obj.cargo
        if hasattr(cargo, "get_transport_type_display"):
            label = cargo.get_transport_type_display()  # напр. "Тент"
            return label[:1] if label else ""
        # fallback: просто первая буква кода
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

    def get_carrier_name(self, obj: Offer) -> str:
        """
        Название перевозчика для колонки «Перевозчик».
        """
        u = obj.carrier
        if not u:
            return ""
        return (
            getattr(u, "company_name", None)
            or getattr(u, "company", None)
            or getattr(u, "name", None)
            or getattr(u, "username", "")
        )

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
        # если есть enum Offer.Initiator, используем его
        try:
            from .models import Offer as OfferModel  # избегаем цикличного импорта типов

            if init == OfferModel.Initiator.CUSTOMER:
                return "Предложение от заказчика"
            if init == OfferModel.Initiator.CARRIER:
                return "Предложение от посредника"
        except Exception:
            pass

        # fallback по строковому коду
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
            # Для вкладки «Я предложил» это и есть тот самый "Ответ получен"
            return "Ответ получен"

        # Если одна из сторон уже приняла, а другая ещё нет — ждём ответа
        if obj.accepted_by_carrier and not obj.accepted_by_customer:
            return "Ожидает ответа"

        if obj.accepted_by_customer and not obj.accepted_by_carrier:
            return "Ожидает ответа"

        return "Ожидает ответа"


class OfferDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = "__all__"
        read_only_fields = (
            "carrier",
            "initiator",
            "accepted_by_customer",
            "accepted_by_carrier",
            "is_active",
            "created_at",
            "updated_at",
        )


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


class OfferRejectResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
