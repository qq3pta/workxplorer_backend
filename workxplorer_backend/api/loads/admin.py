from django.contrib import admin
from django.db.models import F, FloatField
from django.db.models.expressions import Func

from .models import Cargo


class GeoDistance(Func):
    """
    ST_Distance(a::geography, b::geography) -> расстояние в метрах.
    Работает нативно с PointField(geography=True).
    """

    function = "ST_Distance"
    output_field = FloatField()


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "origin_city",
        "destination_city",
        "load_date",
        "transport_type",
        "weight_kg",
        "price_value",
        "price_currency",
        "contact_pref",
        "is_hidden",
        "status",
        "moderation_status",
        "path_km_display",
        "age_minutes_display",
        "created_at",
    )
    list_filter = (
        "status",
        "moderation_status",
        "transport_type",
        "price_currency",
        "is_hidden",
        "load_date",
        "origin_city",
        "destination_city",
    )
    search_fields = (
        "product",
        "origin_city",
        "destination_city",
        "destination_address",
        "origin_address",
        "customer__username",
        "customer__email",
    )
    ordering = ("-refreshed_at",)
    date_hierarchy = "created_at"
    list_select_related = ("customer",)
    readonly_fields = ("origin_point", "dest_point")

    def get_queryset(self, request):
        """
        Аннотируем queryset расстоянием в метрах, чтобы вывести км в list_display.
        Если одна из точек NULL — значение будет NULL и в колонке покажем "-".
        """
        qs = super().get_queryset(request)
        return qs.annotate(path_m=GeoDistance(F("origin_point"), F("dest_point")))

    def path_km_display(self, obj):
        m = getattr(obj, "path_m", None)
        return "-" if m is None else f"{m / 1000:.1f}"

    path_km_display.short_description = "Путь (км)"
    path_km_display.admin_order_field = "path_m"

    def age_minutes_display(self, obj):
        return obj.age_minutes

    age_minutes_display.short_description = "Опубликованное время"
    age_minutes_display.admin_order_field = "refreshed_at"
