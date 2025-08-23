from django.db import models
from django.conf import settings
from django.utils import timezone
from .choices import TransportType, Currency, ContactPref, ModerationStatus

class CargoStatus(models.TextChoices):
    POSTED    = "POSTED",    "Опубликована"
    MATCHED   = "MATCHED",   "В работе"
    DELIVERED = "DELIVERED", "Доставлено"
    COMPLETED = "COMPLETED", "Завершено"

class Cargo(models.Model):
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cargos",
    )

    title = models.CharField(max_length=120)          # Наименование груза
    description = models.TextField(blank=True)        # Комментарии
    origin_address = models.CharField(max_length=255)
    origin_city = models.CharField(max_length=100)
    destination_address = models.CharField(max_length=255)
    destination_city = models.CharField(max_length=100)
    load_date = models.DateField()
    delivery_date = models.DateField(null=True, blank=True)
    transport_type = models.CharField(max_length=10, choices=TransportType.choices)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=2)
    price_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    price_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    contact_pref = models.CharField(max_length=10, choices=ContactPref.choices)
    is_hidden = models.BooleanField(default=False)

    moderation_status = models.CharField(
        max_length=10,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
    )

    refreshed_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=CargoStatus.choices, default=CargoStatus.POSTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["moderation_status", "transport_type", "load_date"]),
            models.Index(fields=["origin_city", "destination_city"]),
            models.Index(fields=["is_hidden"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.origin_city} → {self.destination_city})"

    @property
    def age_minutes(self) -> int:
        base = self.refreshed_at or self.created_at
        return int((timezone.now() - base).total_seconds() // 60)