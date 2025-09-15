from django.contrib import admin
from .models import RouteCache

@admin.register(RouteCache)
class RouteCacheAdmin(admin.ModelAdmin):
    list_display = ("provider", "distance_km", "duration_min", "updated_at", "key")
    list_filter = ("provider", "updated_at")
    search_fields = ("key",)
    readonly_fields = ("updated_at",)