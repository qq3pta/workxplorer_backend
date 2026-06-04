from django.contrib import admin

from .models import ExpoPushTicket, Notification, NotificationPreference, PushDevice


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "type", "title", "is_read", "created_at")
    list_filter = ("type", "is_read", "created_at")
    search_fields = ("title", "message", "user__username")


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "platform", "is_active", "last_seen_at", "disabled_at")
    list_filter = ("platform", "is_active", "created_at")
    search_fields = ("user__email", "user__username", "expo_push_token", "device_id")
    ordering = ("-last_seen_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "push_enabled",
        "chat_push_enabled",
        "order_push_enabled",
        "offer_push_enabled",
    )
    search_fields = ("user__email", "user__username")


@admin.register(ExpoPushTicket)
class ExpoPushTicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "device",
        "notification",
        "ticket_id",
        "status",
        "receipt_status",
        "created_at",
        "checked_at",
    )
    list_filter = ("status", "receipt_status", "created_at", "checked_at")
    search_fields = ("ticket_id", "device__expo_push_token", "message", "receipt_message")
    ordering = ("-created_at",)
