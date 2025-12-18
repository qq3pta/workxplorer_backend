from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from unidecode import unidecode

from api.geo.management.commands.import_cities import COUNTRY_NORMALIZATION
from api.geo.models import GeoPlace
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
            if obj.origin_point and obj.dest_point:
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
    price_uzs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    weight_tons = serializers.FloatField(required=False, write_only=True, min_value=0.001)
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
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
            "payment_method",
            "is_hidden",
        )
        read_only_fields = ("route_km", "price_uzs", "uuid")

    def _val_or_instance(self, attrs: dict[str, Any], name: str):
        if name in attrs:
            return attrs[name]
        if self.instance:
            return getattr(self.instance, name, None)
        return None

    def _need_regeocode(self, attrs: dict[str, Any]):
        changed_origin = any(
            k in attrs for k in ("origin_city", "origin_country", "origin_address")
        )
        changed_dest = any(
            k in attrs for k in ("destination_city", "destination_country", "destination_address")
        )
        if self.instance is None:
            return True, True
        return changed_origin, changed_dest

    def _smart_find_place(self, country: str, city: str) -> GeoPlace | None:
        country = COUNTRY_NORMALIZATION.get(country, country).strip()
        city_norm = city.strip().lower()
        city_trans = unidecode(city_norm).lower()

        qs = GeoPlace.objects.filter(country__iexact=country)

        return (
            qs.filter(name__iexact=city).first()
            or qs.filter(name_latin__iexact=city_trans).first()
            or qs.filter(name__icontains=city_norm).first()
            or qs.filter(name_latin__icontains=city_trans).first()
        )

    def _geocode_origin(self, attrs):
        country = (attrs.get("origin_country") or "").strip()
        city = (attrs.get("origin_city") or "").strip()

        if not city:
            raise serializers.ValidationError({"origin_city": "Укажите город отправления."})

        gp = self._smart_find_place(country, city)
        if gp:
            return gp.point

        try:
            return geocode_city(country=country, city=city)
        except GeocodingError as err:
            raise serializers.ValidationError(
                {"origin_city": f"Город '{city}' не найден. Проверьте написание."}
            ) from err

    def _geocode_dest(self, attrs):
        country = (attrs.get("destination_country") or "").strip()
        city = (attrs.get("destination_city") or "").strip()

        if not city:
            raise serializers.ValidationError({"destination_city": "Укажите город доставки."})

        gp = self._smart_find_place(country, city)
        if gp:
            return gp.point

        try:
            return geocode_city(country=country, city=city)
        except GeocodingError as err:
            raise serializers.ValidationError(
                {"destination_city": f"Город '{city}' не найден. Проверьте написание."}
            ) from err

    def validate(self, attrs):
        required = [
            "origin_address",
            "destination_address",
            "load_date",
            "transport_type",
            "contact_pref",
        ]

        if self.instance is None:
            missing = [f for f in required if attrs.get(f) in ("", None)]
            if missing:
                raise serializers.ValidationError(
                    {f: "Обязательное поле по ТЗ 2.6.13" for f in missing}
                )

        wt = attrs.get("weight_tons")
        if wt is not None:
            if isinstance(wt, float) or isinstance(wt, int):  # FIXED UP038
                wt = Decimal(f"{wt:.6f}")
            else:
                wt = Decimal(str(wt))
            attrs["weight_kg"] = wt * Decimal("1000")

        ld = self._val_or_instance(attrs, "load_date")
        today = timezone.localdate()
        if ld and ld < today:
            raise serializers.ValidationError(
                {"load_date": "Дата загрузки не может быть в прошлом."}
            )

        dd = self._val_or_instance(attrs, "delivery_date")
        if dd and ld and dd < ld:
            raise serializers.ValidationError(
                {"delivery_date": "Дата доставки не может быть раньше даты загрузки."}
            )

        wk = attrs.get("weight_kg")
        if wk is not None and Decimal(str(wk)) <= 0:
            raise serializers.ValidationError({"weight_kg": "Вес должен быть больше нуля."})

        price = attrs.get("price_value")
        if price is not None and price < 0:
            raise serializers.ValidationError({"price_value": "Цена не может быть отрицательной."})

        ax = attrs.get("axles")
        if ax not in (None, ""):
            try:
                ax_i = int(ax)
            except ValueError as err:
                raise serializers.ValidationError({"axles": "Некорректное значение осей."}) from err

            if not (3 <= ax_i <= 10):
                raise serializers.ValidationError({"axles": "Оси должны быть в диапазоне 3–10."})

        vol = attrs.get("volume_m3")
        if vol is not None:
            try:
                if Decimal(str(vol)) <= 0:
                    raise serializers.ValidationError(
                        {"volume_m3": "Объём должен быть больше нуля."}
                    )
            except Exception as err:
                raise serializers.ValidationError({"volume_m3": "Введите число."}) from err

        return attrs

    def create(self, validated_data):
        user = self.context["request"].user

        wt = validated_data.pop("weight_tons", None)
        if wt is not None:
            if isinstance(wt, float) or isinstance(wt, int):  # FIXED UP038
                wt = Decimal(f"{wt:.6f}")
            else:
                wt = Decimal(str(wt))
            validated_data["weight_kg"] = wt * Decimal("1000")

        origin_point = self._geocode_origin(validated_data)
        dest_point = self._geocode_dest(validated_data)

        if not origin_point or not dest_point:
            raise serializers.ValidationError("Не удалось определить координаты маршрута.")

        cargo = Cargo.objects.create(
            customer=user,
            origin_point=origin_point,
            dest_point=dest_point,
            moderation_status=ModerationStatus.PENDING,
            **validated_data,
        )

        cargo.update_route_cache(save=True)
        cargo.update_price_uzs()
        return cargo

    def update(self, instance, validated_data):
        wt = validated_data.pop("weight_tons", None)
        if wt is not None:
            if isinstance(wt, float) or isinstance(wt, int):  # FIXED UP038
                wt = Decimal(f"{wt:.6f}")
            else:
                wt = Decimal(str(wt))
            validated_data["weight_kg"] = wt * Decimal("1000")

        need_origin, need_dest = self._need_regeocode(validated_data)

        if need_origin:
            instance.origin_point = self._geocode_origin(validated_data)

        if need_dest:
            instance.dest_point = self._geocode_dest(validated_data)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.save()

        if instance.load_date and instance.load_date < timezone.localdate():
            raise serializers.ValidationError(
                {"load_date": "Дата загрузки не может быть в прошлом."}
            )

        if instance.origin_point and instance.dest_point and (need_origin or need_dest):
            instance.update_route_cache(save=True)

        instance.update_price_uzs()
        return instance


class CargoListSerializer(RouteKmMixin, serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    price_uzs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    uuid = serializers.UUIDField(read_only=True)
    age_minutes = serializers.IntegerField(read_only=True)
    user_name = serializers.SerializerMethodField()
    user_id = serializers.SerializerMethodField()
    path_km = serializers.FloatField(read_only=True)
    origin_dist_km = serializers.FloatField(read_only=True)
    origin_radius_km = serializers.FloatField(read_only=True)
    dest_radius_km = serializers.FloatField(read_only=True)

    has_offers = serializers.SerializerMethodField()
    offers_count = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()

    company_rating = serializers.FloatField(read_only=True)
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()

    weight_t = serializers.SerializerMethodField()
    price_per_km = serializers.SerializerMethodField()
    is_hidden = serializers.BooleanField(read_only=True)

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
            "payment_method",
            "price_per_km",
            "origin_dist_km",
            "origin_radius_km",
            "dest_radius_km",
            "is_hidden",
            "user_name",
            "user_id",
        )
        read_only_fields = fields

    def get_has_offers(self, obj) -> bool:
        oa = getattr(obj, "offers_active", None)
        if oa is not None:
            return oa > 0
        return obj.offers.filter(is_active=True).exists()

    @extend_schema_field(int)
    def get_offers_count(self, obj) -> int:
        oa = getattr(obj, "offers_active", None)
        return int(oa or 0)

    def get_company_name(self, obj) -> str:
        u = getattr(obj, "customer", None)
        if not u:
            return ""
        return (
            getattr(u, "company_name", None)
            or getattr(u, "company", None)
            or getattr(u, "name", None)
            or getattr(u, "username", "")
        )

    def get_phone(self, obj) -> str:
        u = obj.customer
        return getattr(u, "phone", "") or getattr(u, "phone_number", "")

    def get_email(self, obj) -> str:
        return getattr(obj.customer, "email", "") or ""

    @extend_schema_field(float)
    def get_weight_t(self, obj):
        try:
            return round(float(obj.weight_kg) / 1000, 3)
        except Exception:
            return None

    def _get_author(self, obj):
        return obj.created_by if obj.created_by else obj.customer

    def get_user_name(self, obj):
        author = self._get_author(obj)

        # если есть полноценное имя
        full = getattr(author, "get_full_name", None)
        if callable(full):
            name = full()
            if name:
                return name

        # имя из поля name
        name = getattr(author, "name", None)
        if name:
            return name

        # username — fallback
        return getattr(author, "username", "")

    def get_user_id(self, obj):
        author = self._get_author(obj)
        return author.id

    @extend_schema_field(Decimal)
    def get_price_per_km(self, obj):
        price = obj.price_value
        dist = obj.route_km or obj.route_km_cached or obj.path_km
        if not price or not dist:
            return None

        if float(dist) == 0:
            return None

        try:
            return (Decimal(str(price)) / Decimal(str(dist))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except Exception:
            return None


class CargoInviteGenerateRequestSerializer(serializers.Serializer):
    """
    Пустой, потому что запрос не принимает тело.
    Нужен только для корректной документации.
    """

    pass


class CargoInviteGenerateResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    invite_url = serializers.CharField()
