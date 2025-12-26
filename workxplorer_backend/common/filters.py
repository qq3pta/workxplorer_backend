from decimal import Decimal

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db.models import Q

from common.utils import convert_to_uzs


def apply_loads_filters(qs, p):
    # ======================
    # HAS OFFERS
    # ======================
    has_offers = p.get("has_offers")
    if has_offers is not None:
        has_offers = str(has_offers).lower()
        if has_offers in ("true", "1"):
            qs = qs.filter(offers_active__gt=0)
        elif has_offers in ("false", "0"):
            qs = qs.filter(offers_active=0)

    # ======================
    # UUID / ГОРОДА / ДАТЫ
    # ======================
    if p.get("uuid"):
        qs = qs.filter(uuid=p["uuid"])

    if p.get("origin_city"):
        qs = qs.filter(origin_city__iexact=p["origin_city"])

    if p.get("destination_city"):
        qs = qs.filter(destination_city__iexact=p["destination_city"])

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
    if p.get("axles_min"):
        qs = qs.filter(axles__gte=p["axles_min"])
    if p.get("axles_max"):
        qs = qs.filter(axles__lte=p["axles_max"])

    # ======================
    # VOLUME
    # ======================
    if p.get("volume_min"):
        qs = qs.filter(volume_m3__gte=p["volume_min"])
    if p.get("volume_max"):
        qs = qs.filter(volume_m3__lte=p["volume_max"])

    # ======================
    # PRICE + CURRENCY
    # ======================
    min_price = p.get("min_price")
    max_price = p.get("max_price")
    currency = p.get("price_currency")

    if currency:
        try:
            if min_price not in (None, ""):
                qs = qs.filter(price_uzs_anno__gte=convert_to_uzs(Decimal(min_price), currency))
            if max_price not in (None, ""):
                qs = qs.filter(price_uzs_anno__lte=convert_to_uzs(Decimal(max_price), currency))
        except Exception:
            pass

    # ======================
    # COMPANY / TEXT SEARCH
    # ======================
    q = p.get("company") or p.get("q")
    if q:
        qs = qs.filter(
            Q(customer__company_name__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__email__icontains=q)
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
            qs = qs.annotate(origin_dist_km=Distance("origin_point", center) / 1000.0).filter(
                origin_dist_km__lte=float(o_r)
            )
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
    # SORTING
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
    }

    order_alias = {
        "age_minutes": "age_minutes_anno",
        "-age_minutes": "-age_minutes_anno",
    }

    order = order_alias.get(p.get("order"), p.get("order"))

    if order in allowed:
        qs = qs.order_by(order)
    else:
        qs = qs.order_by("-refreshed_at", "-created_at")

    return qs
