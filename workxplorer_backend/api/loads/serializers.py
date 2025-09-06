from rest_framework import serializers
from django.contrib.gis.geos import Point

from .models import Cargo
from .choices import TransportType, ContactPref, ModerationStatus, Currency
from api.geo.services import geocode_city, GeocodingError


class CargoPublishSerializer(serializers.ModelSerializer):
    """
    Создание/обновление заявки.
    - Пользователь вводит только страну/город/адрес (координаты не требуются).
    - Сервер сам геокодит и заполняет origin_point/dest_point.
    """
    class Meta:
        model = Cargo
        fields = (
            "product", "description",

            "origin_country", "origin_city",
            "origin_address",

            "destination_country", "destination_city",
            "destination_address",

            "load_date", "delivery_date",
            "transport_type",
            "weight_kg",
            "price_value", "price_currency",
            "contact_pref", "is_hidden",
        )

    def _val_or_instance(self, attrs, name):
        """Берём значение из attrs, а если апдейт и поля нет — из instance."""
        if name in attrs:
            return attrs[name]
        if self.instance is not None:
            return getattr(self.instance, name, None)
        return None

    def _need_regeocode(self, attrs) -> tuple[bool, bool]:
        """Нужно ли пересчитать origin_point и/или dest_point."""
        o_fields = {"origin_country", "origin_city", "origin_address"}
        d_fields = {"destination_country", "destination_city", "destination_address"}
        origin_changed = any(f in attrs for f in o_fields)
        dest_changed   = any(f in attrs for f in d_fields)
        if self.instance is None:
            return True, True
        return origin_changed, dest_changed

    def _geocode_origin(self, attrs) -> Point:
        country = (attrs.get("origin_country") or self._val_or_instance(attrs, "origin_country") or "").strip()
        city    = (attrs.get("origin_city")    or self._val_or_instance(attrs, "origin_city")    or "").strip()
        if not city:
            raise serializers.ValidationError({"origin_city": "Укажите город погрузки"})
        try:
            return geocode_city(country=country, city=city, country_code=None)
        except GeocodingError as e:
            raise serializers.ValidationError({"origin_city": str(e)})

    def _geocode_dest(self, attrs) -> Point:
        country = (attrs.get("destination_country") or self._val_or_instance(attrs, "destination_country") or "").strip()
        city    = (attrs.get("destination_city")    or self._val_or_instance(attrs, "destination_city")    or "").strip()
        if not city:
            raise serializers.ValidationError({"destination_city": "Укажите город разгрузки"})
        try:
            return geocode_city(country=country, city=city, country_code=None)
        except GeocodingError as e:
            raise serializers.ValidationError({"destination_city": str(e)})

    def validate(self, attrs):
        required = [
            "origin_address", "destination_address",
            "load_date", "transport_type",
            "weight_kg", "contact_pref",
        ]
        if self.instance is None:
            missing = [f for f in required if attrs.get(f) in (None, "", [])]
            if missing:
                raise serializers.ValidationError({f: "Обязательное поле по ТЗ 2.6.13" for f in missing})

        transport_type = self._val_or_instance(attrs, "transport_type")
        contact_pref   = self._val_or_instance(attrs, "contact_pref")
        price_currency = self._val_or_instance(attrs, "price_currency")

        if transport_type is not None and transport_type not in TransportType.values:
            raise serializers.ValidationError({"transport_type": "Недопустимый тип транспорта"})
        if contact_pref is not None and contact_pref not in ContactPref.values:
            raise serializers.ValidationError({"contact_pref": "Недопустимый способ связи"})
        if price_currency is not None and price_currency not in Currency.values:
            raise serializers.ValidationError({"price_currency": "Недопустимая валюта"})

        weight = self._val_or_instance(attrs, "weight_kg")
        if weight is not None and weight <= 0:
            raise serializers.ValidationError({"weight_kg": "Вес должен быть > 0"})

        price = self._val_or_instance(attrs, "price_value")
        if price is not None and price < 0:
            raise serializers.ValidationError({"price_value": "Цена не может быть отрицательной"})

        ld = self._val_or_instance(attrs, "load_date")
        dd = self._val_or_instance(attrs, "delivery_date")
        if dd and ld and dd < ld:
            raise serializers.ValidationError({"delivery_date": "Дата доставки не может быть раньше даты загрузки."})

        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        origin_point = self._geocode_origin(validated_data)
        dest_point   = self._geocode_dest(validated_data)

        return Cargo.objects.create(
            customer=user,
            origin_point=origin_point,
            dest_point=dest_point,
            moderation_status=ModerationStatus.PENDING,
            **validated_data,
        )

    def update(self, instance, validated_data):
        need_origin, need_dest = self._need_regeocode(validated_data)

        if need_origin:
            instance.origin_point = self._geocode_origin(validated_data)
        if need_dest:
            instance.dest_point = self._geocode_dest(validated_data)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.save()
        return instance


class CargoListSerializer(serializers.ModelSerializer):
    """
    Листинг/борда. Поля рассчитываются так:
    - path_km    — приходит из аннотации queryset'а: ST_Distance(origin_point::geography, dest_point::geography) / 1000.0
    - origin_dist_km — приходит из аннотации (если задан фильтр радиуса origin), иначе будет None
    - has_offers — вычисляется тут (если есть аннотация offers_active — используем её; иначе exists())
    """
    age_minutes = serializers.IntegerField(read_only=True)
    path_km = serializers.FloatField(read_only=True, required=False)
    origin_dist_km = serializers.FloatField(read_only=True, required=False)
    has_offers = serializers.SerializerMethodField()

    class Meta:
        model = Cargo
        fields = (
            "id",
            "product", "description",

            "origin_country", "origin_city", "origin_address",
            "destination_country", "destination_city", "destination_address",

            "load_date", "delivery_date",
            "transport_type",
            "weight_kg",
            "price_value", "price_currency",
            "contact_pref", "is_hidden",

            "moderation_status", "status",
            "age_minutes", "created_at", "refreshed_at",

            "has_offers",
            "path_km",
            "origin_dist_km",
        )
        read_only_fields = fields

    def get_has_offers(self, obj) -> bool:
        offers_active = getattr(obj, "offers_active", None)
        if offers_active is not None:
            return offers_active > 0
        return obj.offers.filter(is_active=True).exists()