from decimal import Decimal
from django.db.models import Q
from common.utils import convert_to_uzs


def apply_common_search_filters(qs, p):
    # ---- ТЕКСТ ПОИСК ----
    q = p.get("q") or p.get("company")
    if q:
        qs = qs.filter(
            Q(customer__company_name__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__email__icontains=q)
        )

    # ---- ВЕС (ТОННЫ → КГ) ----
    try:
        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=float(p["min_weight"]) * 1000)
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=float(p["max_weight"]) * 1000)
    except ValueError:
        pass

    # ---- ЦЕНА (ВАЛЮТА → UZS) ----
    currency = p.get("price_currency")
    if currency:
        try:
            if p.get("min_price"):
                qs = qs.filter(
                    price_uzs_anno__gte=convert_to_uzs(Decimal(p["min_price"]), currency)
                )
            if p.get("max_price"):
                qs = qs.filter(
                    price_uzs_anno__lte=convert_to_uzs(Decimal(p["max_price"]), currency)
                )
        except Exception as e:
            print("PRICE FILTER ERROR:", e)

    # ---- НАЛИЧИЕ ПРЕДЛОЖЕНИЙ ----
    has_offers = p.get("has_offers")
    if has_offers is not None:
        has_offers = str(has_offers).lower()
        if has_offers in ("true", "1"):
            qs = qs.filter(offers_active__gt=0)
        elif has_offers in ("false", "0"):
            qs = qs.filter(offers_active=0)

    return qs
