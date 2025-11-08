from django.contrib import admin
from django.utils.html import format_html

from .models import Offer


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cargo_link",
        "carrier",
        "price_value",
        "price_currency",
        "accepted_by_customer",
        "accepted_by_carrier",
        "is_handshake_display",
        "is_active",
        "created_at",
    )
    list_filter = (
        "is_active",
        "accepted_by_customer",
        "accepted_by_carrier",
        "price_currency",
        "initiator",
        "cargo__status",
        "created_at",
    )
    search_fields = (
        "cargo__uuid",
        "cargo__origin_city",
        "cargo__destination_city",
        "cargo__customer__username",
        "cargo__customer__email",
        "carrier__username",
        "carrier__email",
    )
    autocomplete_fields = ("cargo", "carrier")
    ordering = ("-created_at",)
    list_select_related = ("cargo", "carrier")
    list_per_page = 50
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")

    def cargo_link(self, obj):
        if obj.cargo_id:
            return format_html(
                '<a href="/admin/loads/cargo/{}/change/">{} → {}</a>',
                obj.cargo_id,
                getattr(obj.cargo, "origin_city", "") or "—",
                getattr(obj.cargo, "destination_city", "") or "—",
            )
        return "—"

    cargo_link.short_description = "Груз"

    def is_handshake_display(self, obj):
        return "🤝" if (obj.accepted_by_customer and obj.accepted_by_carrier) else "—"

    is_handshake_display.short_description = "Сделка"
