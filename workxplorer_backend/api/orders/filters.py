import django_filters

from .models import Order


class OrderFilter(django_filters.FilterSet):
    role = django_filters.CharFilter(method="filter_role")
    status = django_filters.CharFilter(field_name="status")
    cargo = django_filters.NumberFilter(field_name="cargo_id")
    load = django_filters.NumberFilter(method="filter_load")
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Order
        fields = ["status", "cargo"]

    def filter_role(self, qs, name, value):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return qs.none()
        if value == "customer":
            return qs.filter(customer_id=user.id)
        if value == "carrier":
            return qs.filter(carrier_id=user.id)
        return qs

    def filter_load(self, qs, name, value):
        try:
            return qs.filter(cargo_id=int(value))
        except (TypeError, ValueError):
            return qs.none()
