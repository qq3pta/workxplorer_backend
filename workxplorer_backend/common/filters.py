from decimal import Decimal

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db.models import Q, F
from django.utils import timezone

from common.utils import convert_to_uzs


def apply_loads_filters(qs, p, hide_expired=False):
    """
    Оптимизированная функция фильтрации грузов.
    Использует индексы и минимизирует количество запросов.
    """
    # ======================
    # HAS OFFERS
    # ======================
    if hide_expired:
        today = timezone.localdate()
        qs = qs.filter(load_date__gte=today)

    has_offers = p.get("has_offers")
    if has_offers is not None:
        has_offers = str(has_offers).lower()
        if has_offers in ("true", "1"):
            qs = qs.filter(offers_active__gt=0)
        elif has_offers in ("false", "0"):
            qs = qs.filter(offers_active=0)

    # ======================
    # UUID / ГОРОДА / ДАТЫ (оптимизировано с индексами)
    # ======================
    if p.get("uuid"):
        # UUID - уникальный индекс, очень быстро
        qs = qs.filter(uuid=p["uuid"])

    # Используем latin версии для поиска (индексированы)
    if p.get("origin_city") and not p.get("origin_radius_km"):
        origin_city = p["origin_city"].strip().lower()
        qs = qs.filter(
            Q(origin_city__iexact=origin_city) | Q(origin_city_latin__iexact=origin_city)
        )

    if p.get("destination_city") and not p.get("dest_radius_km"):
        dest_city = p["destination_city"].strip().lower()
        qs = qs.filter(
            Q(destination_city__iexact=dest_city) | Q(destination_city_latin__iexact=dest_city)
        )

    if p.get("load_date"):
        qs = qs.filter(load_date=p["load_date"])

    if p.get("load_date_from"):
        qs = qs.filter(load_date__gte=p["load_date_from"])

    if p.get("load_date_to"):
        qs = qs.filter(load_date__lte=p["load_date_to"])

    # ======================
    # TRANSPORT
    # ======================
    if p.get("transport_type"):
        qs = qs.filter(transport_type=p["transport_type"])
    if p.get("cargo_category"):
        qs = qs.filter(cargo_category=p["cargo_category"])

    # ======================
    # WEIGHT (t → kg)
    # ======================
    try:
        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=float(p["min_weight"]) * 1000)
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=float(p["max_weight"]) * 1000)
    except ValueError:
        pass

    # ======================
    # AXLES
    # ======================
    min_axles = p.get("min_axles") or p.get("axles_min")
    if min_axles:
        qs = qs.filter(axles__gte=min_axles)

    max_axles = p.get("max_axles") or p.get("axles_max")
    if max_axles:
        qs = qs.filter(axles__lte=max_axles)

    # ======================
    # VOLUME
    # ======================
    min_volume = p.get("min_volume_m3") or p.get("volume_min")
    if min_volume:
        qs = qs.filter(volume_m3__gte=min_volume)

    max_volume = p.get("max_volume_m3") or p.get("volume_max")
    if max_volume:
        qs = qs.filter(volume_m3__lte=max_volume)

    # ======================
    # PRICE + CURRENCY
    # ======================
    min_price = p.get("min_price")
    max_price = p.get("max_price")
    currency = p.get("price_currency")
    currency_selected = p.get("price_currency_selected")

    try:
        if min_price not in (None, ""):
            qs = qs.filter(price_uzs_anno__gte=convert_to_uzs(Decimal(min_price), currency))
        if max_price not in (None, ""):
            qs = qs.filter(price_uzs_anno__lte=convert_to_uzs(Decimal(max_price), currency))
    except Exception:
        pass

    if currency_selected:
        qs = qs.annotate(selected_currency=F("price_currency")).filter(
            selected_currency=currency_selected
        )

    # ======================
    # COMPANY / TEXT SEARCH (оптимизировано)
    # ======================
    q = p.get("company") or p.get("q")
    if q:
        # Преобразуем в нижний регистр для более быстрого поиска
        q_lower = q.lower()
        qs = qs.filter(
            Q(customer__company_name__icontains=q_lower)
            | Q(customer__username__icontains=q_lower)
            | Q(customer__email__icontains=q_lower)
        )

    # ======================
    # GEO — ORIGIN
    # ======================
    o_lat = p.get("origin_lat") or p.get("lat")
    o_lng = p.get("origin_lng") or p.get("lng")
    o_r = p.get("origin_radius_km")

    if o_lat and o_lng and o_r:
        try:
            center = Point(float(o_lng), float(o_lat), srid=4326)
            radius = float(o_r)

            qs = qs.annotate(
                origin_dist_km=Distance("origin_point", center) / 1000.0,
            ).filter(origin_dist_km__lte=radius)
        except Exception:
            pass

    # ======================
    # GEO — DESTINATION
    # ======================
    d_lat = p.get("dest_lat")
    d_lng = p.get("dest_lng")
    d_r = p.get("dest_radius_km")

    if d_lat and d_lng and d_r:
        try:
            center = Point(float(d_lng), float(d_lat), srid=4326)
            qs = qs.annotate(dest_dist_km=Distance("dest_point", center) / 1000.0).filter(
                dest_dist_km__lte=float(d_r)
            )
        except Exception:
            pass

    # ======================
    # SORTING (оптимизировано с индексами)
    # ======================
    allowed = {
        "path_km",
        "-path_km",
        "route_km",
        "-route_km",
        "origin_dist_km",
        "-origin_dist_km",
        "dest_dist_km",
        "-dest_dist_km",
        "price_uzs_anno",
        "-price_uzs_anno",
        "load_date",
        "-load_date",
        "axles",
        "-axles",
        "volume_m3",
        "-volume_m3",
        "age_minutes_anno",
        "-age_minutes_anno",
        "weight_kg",
        "-weight_kg",
    }

    order_alias = {
        "age_minutes": "age_minutes_anno",
        "-age_minutes": "-age_minutes_anno",
    }

    order = order_alias.get(p.get("order"), p.get("order"))

    if order in allowed:
        qs = qs.order_by(order)
    else:
        # Используем индексированную сортировку по умолчанию
        qs = qs.order_by("-refreshed_at", "-created_at")

    return qs
