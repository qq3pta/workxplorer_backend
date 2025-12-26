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

    return qs
