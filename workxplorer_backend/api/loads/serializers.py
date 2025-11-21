from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.contrib.gis.geos import Point
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.geo.services import GeocodingError, geocode_city

from .choices import ModerationStatus
from .models import Cargo, PaymentMethod


class RouteKmMixin(serializers.Serializer):
    route_km = serializers.SerializerMethodField()

    def get_route_km(self, obj: Cargo) -> float | None:
        val = getattr(obj, "route_km", None)
        if val is not None:
            try:
                return round(float(val), 1)
            except Exception:
                pass

        cached = getattr(obj, "route_km_cached", None)
        if cached is not None:
            try:
                return round(float(cached), 1)
            except Exception:
                pass

        try:
            if getattr(obj, "origin_point", None) and getattr(obj, "dest_point", None):
                from api.routing.services import get_route

                rc = get_route(obj.origin_point, obj.dest_point)
                if rc:
                    return round(float(rc.distance_km), 1)
        except Exception:
            pass

        pk = getattr(obj, "path_km", None)
        try:
            return round(float(pk), 1) if pk is not None else None
        except Exception:
            return None


class CargoPublishSerializer(RouteKmMixin, serializers.ModelSerializer):
    price_uzs = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, required=False
    )
    weight_tons = serializers.FloatField(required=False, write_only=True, min_value=0.001)
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices, default=PaymentMethod.TRANSFER
    )

    class Meta:
        model = Cargo
        fields = (
            "uuid",
            "product",
            "description",
            "origin_country",
            "origin_city",
            "origin_address",
            "destination_country",
            "destination_city",
            "destination_address",
            "load_date",
            "delivery_date",
            "transport_type",
            "weight_kg",
            "weight_tons",
            "axles",
            "volume_m3",
            "price_value",
            "price_currency",
            "price_uzs",
            "contact_pref",
            "is_hidden",
            "payment_method",
        )
        read_only_fields = ("route_km", "price_uzs", "uuid")

    def _val_or_instance(self, attrs: dict[str, Any], name: str) -> Any:
        if name in attrs:
            return attrs[name]
        if self.instance is not None:
            return getattr(self.instance, name, None)
        return None

    def _need_regeocode(self, attrs: dict[str, Any]) -> tuple[bool, bool]:
        o_fields = {"origin_country", "origin_city", "origin_address"}
        d_fields = {"destination_country", "destination_city", "destination_address"}
        origin_changed = any(f in attrs for f in o_fields)
        dest_changed = any(f in attrs for f in d_fields)
        if self.instance is None:
            return True, True
        return origin_changed, dest_changed

    def _geocode_origin(self, attrs: dict[str, Any]) -> Point:
        country = (
            attrs.get("origin_country") or self._val_or_instance(attrs, "origin_country") or ""
        ).strip()
        city = (
            attrs.get("origin_city") or self._val_or_instance(attrs, "origin_city") or ""
        ).strip()
        if not city:
            raise serializers.ValidationError({"origin_city": "Укажите город погрузки"})
        try:
            return geocode_city(country=country, city=city, country_code=None)
        except GeocodingError:
            raise serializers.ValidationError(
                {"origin_city": "Не удалось геокодировать город"}
            ) from None

    def _geocode_dest(self, attrs: dict[str, Any]) -> Point:
        country = (
            attrs.get("destination_country")
            or self._val_or_instance(attrs, "destination_country")
            or ""
        ).strip()
        city = (
            attrs.get("destination_city") or self._val_or_instance(attrs, "destination_city") or ""
        ).strip()
        if not city:
            raise serializers.ValidationError({"destination_city": "Укажите город разгрузки"})
        try:
            return geocode_city(country=country, city=city, country_code=None)
        except GeocodingError:
            raise serializers.ValidationError(
                {"destination_city": "Не удалось геокодировать город"}
            ) from None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        required = [
            "origin_address",
            "destination_address",
            "load_date",
            "transport_type",
            "contact_pref",
        ]

        wt = attrs.get("weight_tons")
        if wt is not None:
            attrs["weight_kg"] = Decimal(str(wt)) * Decimal("1000")

        if self.instance is None:
            missing = [f for f in required if attrs.get(f) in (None, "", [])]
            if missing:
                raise serializers.ValidationError(
                    {f: "Обязательное поле по ТЗ 2.6.13" for f in missing}
                )
            if attrs.get("weight_kg") in (None, ""):
                raise serializers.ValidationError(
                    {"weight_kg": "Укажите вес (в кг) или weight_tons (в тоннах)."}
                )

        ld = self._val_or_instance(attrs, "load_date")
        if ld and ld < timezone.now().date():
            raise serializers.ValidationError(
                {"load_date": "Дата загрузки не может быть в прошлом."}
            )

        dd = self._val_or_instance(attrs, "delivery_date")
        if dd and ld and dd < ld:
            raise serializers.ValidationError(
                {"delivery_date": "Дата доставки не может быть раньше даты загрузки."}
            )

        wk = attrs.get("weight_kg", self._val_or_instance(attrs, "weight_kg"))
        if wk is not None and Decimal(str(wk)) <= 0:
            raise serializers.ValidationError({"weight_kg": "Вес должен быть больше нуля."})

        price = self._val_or_instance(attrs, "price_value")
        if price is not None and price < 0:
            raise serializers.ValidationError({"price_value": "Цена не может быть отрицательной."})

        ax = attrs.get("axles", self._val_or_instance(attrs, "axles"))
        if ax is not None and not (3 <= int(ax) <= 10):
            raise serializers.ValidationError({"axles": "Оси должны быть в диапазоне 3–10."})

        vol = attrs.get("volume_m3", self._val_or_instance(attrs, "volume_m3"))
        if vol is not None:
            try:
                dv = Decimal(str(vol))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError(
                    {"volume_m3": "Некорректное значение объёма."}
                ) from None
            if dv <= 0:
                raise serializers.ValidationError({"volume_m3": "Объём должен быть больше нуля."})

        return attrs

    def create(self, validated_data: dict[str, Any]) -> Cargo:
        user = self.context["request"].user

        wt = validated_data.pop("weight_tons", None)
        if wt is not None and "weight_kg" not in validated_data:
            validated_data["weight_kg"] = Decimal(str(wt)) * Decimal("1000")

        origin_point = self._geocode_origin(validated_data)
        dest_point = self._geocode_dest(validated_data)

        cargo = Cargo.objects.create(
            customer=user,
            origin_point=origin_point,
            dest_point=dest_point,
            moderation_status=ModerationStatus.PENDING,
            **validated_data,
        )

        cargo.update_route_cache(save=True)
        if cargo.route_km_cached is not None:
            cargo.route_km = cargo.route_km_cached

        cargo.update_price_uzs()
        return cargo

    def update(self, instance: Cargo, validated_data: dict[str, Any]) -> Cargo:
        wt = validated_data.pop("weight_tons", None)
        if wt is not None:
            validated_data["weight_kg"] = Decimal(str(wt)) * Decimal("1000")

        need_origin, need_dest = self._need_regeocode(validated_data)
        if need_origin:
            instance.origin_point = self._geocode_origin(validated_data)
        if need_dest:
            instance.dest_point = self._geocode_dest(validated_data)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if need_origin or need_dest:
            instance.update_route_cache(save=True)
            if instance.route_km_cached is not None:
                instance.route_km = instance.route_km_cached

        instance.update_price_uzs()
        return instance


class CargoListSerializer(RouteKmMixin, serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    price_uzs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    uuid = serializers.UUIDField(read_only=True)
    age_minutes = serializers.IntegerField(read_only=True)

    path_km = serializers.FloatField(read_only=True, required=False)
    origin_dist_km = serializers.FloatField(read_only=True, required=False)

    # новые поля радиуса
    origin_radius_km = serializers.FloatField(read_only=True, required=False)
    dest_radius_km = serializers.FloatField(read_only=True, required=False)

    has_offers = serializers.SerializerMethodField()
    offers_count = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()

    # новый рейтинг компании
    company_rating = serializers.FloatField(read_only=True, required=False)

    # вместо contact_value
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()

    weight_t = serializers.SerializerMethodField()
    price_per_km = serializers.SerializerMethodField()

    class Meta:
        model = Cargo
        fields = (
            "id",
            "uuid",
            "product",
            "description",
            "origin_country",
            "origin_city",
            "origin_address",
            "destination_country",
            "destination_city",
            "destination_address",
            "load_date",
            "delivery_date",
            "transport_type",
            "weight_kg",
            "weight_t",
            "axles",
            "volume_m3",
            "price_value",
            "price_currency",
            "price_uzs",
            "contact_pref",
            "is_hidden",
            "company_name",
            "company_rating",
            "phone",
            "email",
            "moderation_status",
            "status",
            "age_minutes",
            "created_at",
            "refreshed_at",
            "has_offers",
            "offers_count",
            "path_km",
            "route_km",
            "price_per_km",
            "origin_dist_km",
            "origin_radius_km",
            "dest_radius_km",
        )
        read_only_fields = fields

    def get_has_offers(self, obj: Cargo) -> bool:
        offers_active = getattr(obj, "offers_active", None)
        return (
            offers_active > 0
            if offers_active is not None
            else obj.offers.filter(is_active=True).exists()
        )

    @extend_schema_field(int)
    def get_offers_count(self, obj: Cargo) -> int:
        oa = getattr(obj, "offers_active", None)
        return int(oa or 0) if oa is not None else obj.offers.filter(is_active=True).count()

    def get_company_name(self, obj: Cargo) -> str:
        u = getattr(obj, "customer", None)
        if not u:
            return ""
        return (
            getattr(u, "company_name", None)
            or getattr(u, "company", None)
            or getattr(u, "name", None)
            or getattr(u, "username", "")
        )

    def get_phone(self, obj: Cargo) -> str:
        u = getattr(obj, "customer", None)
        if not u:
            return ""
        phone = getattr(u, "phone", None) or getattr(u, "phone_number", None)
        return phone or ""

    def get_email(self, obj: Cargo) -> str:
        u = getattr(obj, "customer", None)
        if not u:
            return ""
        email = getattr(u, "email", None)
        return email or ""

    @extend_schema_field(float)
    def get_weight_t(self, obj: Cargo) -> float | None:
        if obj.weight_kg is None:
            return None
        try:
            return round(float(obj.weight_kg) / 1000.0, 3)
        except Exception:
            return None

    @extend_schema_field(Decimal)
    def get_price_per_km(self, obj: Cargo) -> Decimal | None:
        price = getattr(obj, "price_value", None)
        dist = (
            getattr(obj, "route_km", None)
            or getattr(obj, "route_km_cached", None)
            or getattr(obj, "path_km", None)
        )
        try:
            if not price or not dist:
                return None
            per_km = (Decimal(str(price)) / Decimal(str(dist))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            return per_km
        except Exception:
            return None
