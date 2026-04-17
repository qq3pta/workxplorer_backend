from django.contrib import admin

from .models import ConsultationRequest, SupportTicket


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("message", "user__email")


@admin.register(ConsultationRequest)
class ConsultationRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "is_processed", "created_at")
    list_filter = ("is_processed", "created_at")
    search_fields = ("email",)
    list_editable = ("is_processed",)
    ordering = ("-created_at",)
