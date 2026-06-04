from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )

    type = models.CharField(max_length=50)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    payload = models.JSONField(null=True, blank=True)

    cargo = models.ForeignKey(
        "loads.Cargo",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )

    offer = models.ForeignKey(
        "offers.Offer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user} – {self.type}"


class PushDevice(models.Model):
    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        UNKNOWN = "unknown", "Unknown"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_devices"
    )
    expo_push_token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(
        max_length=16,
        choices=Platform.choices,
        default=Platform.UNKNOWN,
    )
    device_id = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    disabled_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def disable(self, error: str = "") -> None:
        self.is_active = False
        self.disabled_at = timezone.now()
        self.error = error
        self.save(update_fields=["is_active", "disabled_at", "error", "updated_at"])

    def __str__(self):
        return f"PushDevice(user={self.user_id}, platform={self.platform})"


class NotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    push_enabled = models.BooleanField(default=True)
    chat_push_enabled = models.BooleanField(default=True)
    order_push_enabled = models.BooleanField(default=True)
    offer_push_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки уведомлений"
        verbose_name_plural = "Настройки уведомлений"

    def __str__(self):
        return f"NotificationPreference(user={self.user_id})"


class ExpoPushTicket(models.Model):
    device = models.ForeignKey(PushDevice, on_delete=models.CASCADE, related_name="expo_tickets")
    notification = models.ForeignKey(
        Notification,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="expo_tickets",
    )
    ticket_id = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=32, blank=True)
    message = models.TextField(blank=True)
    details = models.JSONField(null=True, blank=True)
    receipt_status = models.CharField(max_length=32, blank=True)
    receipt_message = models.TextField(blank=True)
    receipt_details = models.JSONField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["receipt_status", "created_at"]),
        ]

    def __str__(self):
        return self.ticket_id or f"ExpoPushTicket#{self.pk}"
