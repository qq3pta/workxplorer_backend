from django.contrib import admin
from .models import UserRating


@admin.register(UserRating)
class UserRatingAdmin(admin.ModelAdmin):
    list_display = ("id", "rated_user", "rated_by", "order", "score", "created_at")
    list_filter = ("score", "created_at")
    search_fields = ("rated_user__username", "rated_by__username", "order__id")
    ordering = ("-created_at",)
