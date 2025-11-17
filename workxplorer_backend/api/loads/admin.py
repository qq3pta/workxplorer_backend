from django.contrib import admin, messages
from django.db.models import F, FloatField, Avg
from django.db.models.expressions import Func
from django.utils.html import format_html

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
        "uuid",
        "product",
        "origin_city",
        "destination_city",
        "load_date",
        "transport_type",
        "weight_kg",
        "weight_t_display",
        "axles",
        "volume_m3",
        "price_value",
        "price_currency",
        "price_uzs_display",
        "contact_pref",
        "customer_contact_phone",
        "customer_contact_email",
        "is_hidden",
        "status",
        "moderation_status",
        "company_rating_display",
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
        "axles",
        "volume_m3",
    )

    search_fields = (
        "uuid",
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
    list_per_page = 50

    readonly_fields = (
        "uuid",
        "origin_point",
        "dest_point",
        "route_km_cached",
        "route_duration_min_cached",
        "price_uzs",
    )

    actions = ("recalculate_route_km", "recalculate_price_uzs")

    # --------- аннотации / вычисления ----------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            path_m=GeoDistance(F("origin_point"), F("dest_point")),
            company_rating=Avg("customer__ratings_received__score"),
        )

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
        return f"{obj.age_minutes} мин назад"

    age_minutes_display.short_description = "Опубликовано"
    age_minutes_display.admin_order_field = "refreshed_at"

    def price_uzs_display(self, obj):
        """Показывает цену в сумах с форматированием и подсветкой валюты."""
        if obj.price_uzs:
            try:
                value = float(obj.price_uzs)
                return format_html("<b>{:,.0f}</b> сум", value)
            except (ValueError, TypeError):
                return format_html("<b>{}</b> сум", obj.price_uzs)
        return "-"

    price_uzs_display.short_description = "Цена (UZS)"
    price_uzs_display.admin_order_field = "price_uzs"

    def weight_t_display(self, obj):
        try:
            if obj.weight_kg is None:
                return "-"
            return f"{float(obj.weight_kg) / 1000:.3f}"
        except Exception:
            return "-"

    weight_t_display.short_description = "Вес (т)"

    def company_rating_display(self, obj):
        v = getattr(obj, "company_rating", None)
        if v is None:
            return "-"
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return v

    company_rating_display.short_description = "Рейтинг компании"
    company_rating_display.admin_order_field = "company_rating"

    def customer_contact_phone(self, obj):
        u = getattr(obj, "customer", None)
        if not u:
            return "-"
        phone = getattr(u, "phone", None) or getattr(u, "phone_number", None)
        return phone or "-"

    customer_contact_phone.short_description = "Телефон заказчика"

    def customer_contact_email(self, obj):
        u = getattr(obj, "customer", None)
        if not u:
            return "-"
        return getattr(u, "email", "") or "-"

    customer_contact_email.short_description = "Email заказчика"

    # --------- экшны ----------
    def recalculate_route_km(self, request, queryset):
        ok = fail = 0
        for cargo in queryset.iterator():
            try:
                res = cargo.update_route_cache(save=True)
                ok += 1 if res else 0
                if res is None:
                    fail += 1
            except Exception:
                fail += 1
        if ok:
            messages.success(request, f"✅ Пересчитано маршрутов: {ok}")
        if fail:
            messages.warning(request, f"⚠️ Ошибок: {fail}")

    recalculate_route_km.short_description = "Пересчитать маршрут (обновить кэш)"

    def recalculate_price_uzs(self, request, queryset):
        """Массовое обновление конверсии цены в сумах."""
        ok = fail = 0
        for cargo in queryset.iterator():
            try:
                cargo.update_price_uzs()
                ok += 1
            except Exception:
                fail += 1
        if ok:
            messages.success(request, f"💰 Цены пересчитаны: {ok}")
        if fail:
            messages.warning(request, f"⚠️ Ошибок: {fail}")

    recalculate_price_uzs.short_description = "Пересчитать цену (UZS)"
