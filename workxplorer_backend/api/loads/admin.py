from django.contrib import admin
from .models import Cargo

@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "customer",
        "pickup_city", "delivery_city",
        "weight_kg", "price", "status", "created_at",
    )
    list_filter = ("status", "pickup_city", "delivery_city", "created_at")
    search_fields = ("title", "customer__username", "pickup_city", "delivery_city")
    list_editable = ("status",)
    autocomplete_fields = ("customer",)
    date_hierarchy = "created_at"