from django.contrib import admin
from django.db.models import FloatField
from django.db.models.expressions import Func

from .models import Order, OrderDocument, OrderStatusHistory


class GeoDistance(Func):
    """
    ST_Distance(a::geography, b::geography) -> расстояние в метрах.
    Работает с PointField(geography=True), если есть гео-поля.
    """
    function = "ST_Distance"
    output_field = FloatField()


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cargo",
        "customer",
        "carrier",
        "status",
        "currency",
        "price_total",
        "route_distance_km",
        "price_per_km_display",
        "created_at",
    )
    list_filter = (
        "status",
        "currency",
        "created_at",
        "customer",
        "carrier",
    )
    search_fields = (
        "id",
        "cargo__product",
        "customer__username",
        "carrier__username",
    )
    readonly_fields = ("price_per_km",)

    def price_per_km_display(self, obj):
        if obj.price_per_km is None:
            return "-"
        return f"{obj.price_per_km:.2f}"
    price_per_km_display.short_description = "Цена за км"


@admin.register(OrderDocument)
class OrderDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "title",
        "category",
        "category_display",
        "uploaded_by",
        "file_name",
        "file_size",
        "created_at",
    )
    list_filter = ("category", "created_at")
    search_fields = ("title", "order__id", "uploaded_by__username")

    readonly_fields = ("file_name", "file_size", "category_display")

    def category_display(self, obj):
        return obj.get_category_display()
    category_display.short_description = "Категория"

    def file_name(self, obj):
        if obj.file:
            return obj.file.name.split("/")[-1]
        return "-"
    file_name.short_description = "Имя файла"

    def file_size(self, obj):
        if obj.file and hasattr(obj.file, "size"):
            return f"{obj.file.size / 1024:.1f} KB"
        return "-"
    file_size.short_description = "Размер файла"


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "user_name",
        "old_status_label",
        "new_status_label",
        "created_at",
    )
    list_filter = ("old_status", "new_status", "created_at")
    search_fields = ("order__id", "user__username")

    def user_name(self, obj):
        u = obj.user
        if not u:
            return "-"
        return getattr(u, "full_name", None) or getattr(u, "name", None) or getattr(u, "username", "-")
    user_name.short_description = "Пользователь"

    def old_status_label(self, obj):
        return obj.get_old_status_display()
    old_status_label.short_description = "Старый статус"

    def new_status_label(self, obj):
        return obj.get_new_status_display()
    new_status_label.short_description = "Новый статус"