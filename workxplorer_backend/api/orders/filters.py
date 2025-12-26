from decimal import Decimal
import django_filters
from django.db import models
from common.utils import convert_to_uzs

from .models import Order


class OrderFilter(django_filters.FilterSet):
    # --- ТЕКУЩИЕ ---
    role = django_filters.CharFilter(method="filter_role")
    status = django_filters.CharFilter(field_name="status")
    cargo = django_filters.NumberFilter(field_name="cargo_id")
    load = django_filters.NumberFilter(method="filter_load")
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    # ======================
    # ВЕС (ТОННЫ → КГ)
    # ======================
    min_weight = django_filters.NumberFilter(method="filter_min_weight")
    max_weight = django_filters.NumberFilter(method="filter_max_weight")

    # ======================
    # ЦЕНА (ВАЛЮТА → UZS)
    # ======================
    min_price = django_filters.NumberFilter(method="filter_min_price")
    max_price = django_filters.NumberFilter(method="filter_max_price")
    price_currency = django_filters.CharFilter(method="filter_price_currency")

    # ======================
    # ГОРОДА
    # ======================
    origin_city = django_filters.CharFilter(field_name="cargo__origin_city", lookup_expr="iexact")
    destination_city = django_filters.CharFilter(
        field_name="cargo__destination_city", lookup_expr="iexact"
    )

    class Meta:
        model = Order
        fields = [
            "status",
            "cargo",
            "origin_city",
            "destination_city",
        ]

    # ---------- ROLE ----------
    def filter_role(self, qs, name, value):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return qs.none()

        if value == "customer":
            return qs.filter(customer_id=user.id)

        if value == "carrier":
            return qs.filter(carrier_id=user.id)

        if value == "logistic":
            return qs.filter(
                models.Q(logistic_id=user.id)
                | models.Q(created_by_id=user.id)
                | models.Q(cargo__created_by_id=user.id)
                | models.Q(offer__logistic_id=user.id)
                | models.Q(offer__intermediary_id=user.id)
            ).distinct()

        return qs

    # ---------- LOAD ----------
    def filter_load(self, qs, name, value):
        try:
            return qs.filter(cargo_id=int(value))
        except (TypeError, ValueError):
            return qs.none()

    # ---------- WEIGHT ----------
    def filter_min_weight(self, qs, name, value):
        return qs.filter(cargo__weight_kg__gte=Decimal(value) * 1000)

    def filter_max_weight(self, qs, name, value):
        return qs.filter(cargo__weight_kg__lte=Decimal(value) * 1000)

    # ---------- PRICE ----------
    def filter_min_price(self, qs, name, value):
        currency = self.data.get("price_currency")
        if not currency:
            return qs
        return qs.filter(price_total__gte=convert_to_uzs(Decimal(value), currency))

    def filter_max_price(self, qs, name, value):
        currency = self.data.get("price_currency")
        if not currency:
            return qs
        return qs.filter(price_total__lte=convert_to_uzs(Decimal(value), currency))

    def filter_price_currency(self, qs, name, value):
        # фильтруем по полю currency модели Order
        if not value:
            return qs
        return qs.filter(currency=value)
