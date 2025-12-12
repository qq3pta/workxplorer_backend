from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "amount",
        "currency",
        "method",
        "status",
        "confirmed_by_customer",
        "confirmed_by_carrier",
        "created_at",
        "completed_at",
    )

    list_filter = ("status", "method", "currency", "created_at")

    search_fields = ("order__id", "external_transaction_id")

    readonly_fields = (
        "created_at",
        "completed_at",
        "status",
        "confirmed_by_customer",
        "confirmed_by_carrier",
    )

    ordering = ("-created_at",)
