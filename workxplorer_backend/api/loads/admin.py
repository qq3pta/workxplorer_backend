from django.contrib import admin, messages
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
        "route_km_cached_display",
        "route_duration_min_cached_display",
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
    readonly_fields = ("origin_point", "dest_point", "route_km_cached", "route_duration_min_cached")

    actions = ("recalculate_route_km",)

    # --------- QS аннотация прямой дистанции (фолбэк) ----------
    def get_queryset(self, request):
        """
        Аннотируем queryset расстоянием в метрах, чтобы вывести км в list_display.
        Если одна из точек NULL — значение будет NULL и в колонке покажем "-".
        """
        qs = super().get_queryset(request)
        return qs.annotate(path_m=GeoDistance(F("origin_point"), F("dest_point")))

    # --------- Колонки list_display ----------
    def path_km_display(self, obj):
        m = getattr(obj, "path_m", None)
        return "-" if m is None else f"{m / 1000:.1f}"

    path_km_display.short_description = "Путь (км, прямая)"
    path_km_display.admin_order_field = "path_m"

    def route_km_cached_display(self, obj):
        v = getattr(obj, "route_km_cached", None)
        return "-" if v is None else f"{float(v):.1f}"

    route_km_cached_display.short_description = "Маршрут (км, кэш)"

    def route_duration_min_cached_display(self, obj):
        v = getattr(obj, "route_duration_min_cached", None)
        return "-" if v is None else f"{float(v):.0f} мин"

    route_duration_min_cached_display.short_description = "Время (мин, кэш)"

    def age_minutes_display(self, obj):
        return obj.age_minutes

    age_minutes_display.short_description = "Опубликованное время"
    age_minutes_display.admin_order_field = "refreshed_at"

    # --------- Админ-экшн: пересчитать маршруты ----------
    def recalculate_route_km(self, request, queryset):
        """
        Пересчитывает маршрут по трассе для выбранных записей и
        сохраняет snapshot в route_km_cached / route_duration_min_cached.
        """
        ok = 0
        fail = 0
        for cargo in queryset.iterator():
            try:
                # метод модели вызывает провайдера (Mapbox/ORS/OSRM) и сохраняет
                res = cargo.update_route_cache(save=True)
                ok += 1 if res is not None else 0
                if res is None:
                    fail += 1
            except Exception:
                fail += 1
        if ok:
            messages.success(request, f"Пересчитано успешно: {ok}")
        if fail:
            messages.warning(request, f"Не удалось пересчитать: {fail}")

    recalculate_route_km.short_description = "Пересчитать маршрут по трассе (обновить кэш)"
