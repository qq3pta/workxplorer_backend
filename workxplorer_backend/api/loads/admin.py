from django.contrib import admin
from .models import Cargo

@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = (
        "id", "product",
        "origin_city", "destination_city", "load_date",
        "transport_type", "weight_kg",
        "price_value",
        "contact_pref", "is_hidden",
        "status", "moderation_status",
        "age_minutes_display",
        "created_at",
    )
    list_filter = (
        "status", "moderation_status", "transport_type",
        "is_hidden", "load_date",
        "origin_city", "destination_city",
    )
    search_fields = ("product", "origin_city", "destination_city", "customer__username", "customer__email")
    ordering = ("-refreshed_at",)
    date_hierarchy = "created_at"

    def age_minutes_display(self, obj):
        return obj.age_minutes
    age_minutes_display.short_description = "Опубликованное время"
    age_minutes_display.admin_order_field = "refreshed_at"