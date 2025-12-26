from decimal import Decimal
from django.db.models import Q
from common.utils import convert_to_uzs


def apply_common_search_filters(qs, p):
    # ======================
    # UUID
    # ======================
    if p.get("uuid"):
        qs = qs.filter(uuid=p["uuid"])

    # ======================
    # ГОРОДА
    # ======================
    if p.get("origin_city"):
        qs = qs.filter(origin_city__iexact=p["origin_city"])

    if p.get("destination_city"):
        qs = qs.filter(destination_city__iexact=p["destination_city"])

    # ======================
    # ДАТЫ ПОГРУЗКИ
    # ======================
    if p.get("load_date"):
        qs = qs.filter(load_date=p["load_date"])

    if p.get("load_date_from"):
        qs = qs.filter(load_date__gte=p["load_date_from"])

    if p.get("load_date_to"):
        qs = qs.filter(load_date__lte=p["load_date_to"])

    # ======================
    # ТЕКСТ ПОИСК
    # ======================
    q = p.get("q") or p.get("company")
    if q:
        qs = qs.filter(
            Q(customer__company_name__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__email__icontains=q)
        )

    # ======================
    # ВЕС (ТОННЫ → КГ)
    # ======================
    try:
        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=float(p["min_weight"]) * 1000)
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=float(p["max_weight"]) * 1000)
    except ValueError:
        pass

    # ======================
    # ЦЕНА (ВАЛЮТА → UZS)
    # ======================
    currency = p.get("price_currency")
    if currency:
        try:
            min_price = p.get("min_price")
            max_price = p.get("max_price")

            if min_price not in (None, ""):
                qs = qs.filter(price_uzs_anno__gte=convert_to_uzs(Decimal(min_price), currency))
            if max_price not in (None, ""):
                qs = qs.filter(price_uzs_anno__lte=convert_to_uzs(Decimal(max_price), currency))
        except Exception as e:
            print("PRICE FILTER ERROR:", e)

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

    return qs


def apply_common_search_filters_offer(qs, p):
    if p.get("uuid"):
        qs = qs.filter(cargo__uuid=p["uuid"])

    if p.get("origin_city"):
        qs = qs.filter(cargo__origin_city__iexact=p["origin_city"])

    if p.get("destination_city"):
        qs = qs.filter(cargo__destination_city__iexact=p["destination_city"])

    if p.get("load_date"):
        qs = qs.filter(cargo__load_date=p["load_date"])

    if p.get("load_date_from"):
        qs = qs.filter(cargo__load_date__gte=p["load_date_from"])

    if p.get("load_date_to"):
        qs = qs.filter(cargo__load_date__lte=p["load_date_to"])

    # цена — ОК (price_uzs_anno у тебя есть)
    currency = p.get("price_currency")
    if currency:
        if p.get("min_price"):
            qs = qs.filter(price_uzs_anno__gte=convert_to_uzs(Decimal(p["min_price"]), currency))
        if p.get("max_price"):
            qs = qs.filter(price_uzs_anno__lte=convert_to_uzs(Decimal(p["max_price"]), currency))

    return qs
