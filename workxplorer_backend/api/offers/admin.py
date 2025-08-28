from django.contrib import admin
from .models import Offer


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cargo", "carrier",
        "price_value", "price_currency",
        "accepted_by_customer", "accepted_by_carrier",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "accepted_by_customer", "accepted_by_carrier", "price_currency", "created_at")
    search_fields = ("cargo__origin_city", "cargo__destination_city", "carrier__username", "carrier__email")
    autocomplete_fields = ("cargo", "carrier")
    ordering = ("-created_at",)