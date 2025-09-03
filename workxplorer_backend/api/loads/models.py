from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.manager import Manager as DjangoManager
from django.utils import timezone
from django.contrib.gis.db import models as gis_models

from .choices import TransportType, ContactPref, ModerationStatus, Currency


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

    product = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    origin_country = models.CharField(max_length=100, default="", blank=True)
    origin_address = models.CharField(max_length=255)
    origin_city = models.CharField(max_length=100)

    destination_country = models.CharField(max_length=100, default="", blank=True)
    destination_address = models.CharField(max_length=255)
    destination_city = models.CharField(max_length=100)

    origin_point = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)
    dest_point   = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)

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

    objects: DjangoManager["Cargo"] = models.Manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["moderation_status", "transport_type", "load_date"]),
            models.Index(fields=["origin_city", "destination_city"]),
            models.Index(fields=["is_hidden"]),
            models.Index(fields=["status"]),
            models.Index(fields=["refreshed_at"]),
            models.Index(fields=["price_value"]),
            models.Index(fields=["price_currency"]),
        ]

    def __str__(self):
        return f"{self.product} ({self.origin_city} → {self.destination_city})"

    def clean(self):
        """Базовая бизнес-валидация полей."""
        if self.delivery_date and self.load_date and self.delivery_date < self.load_date:
            raise ValidationError({"delivery_date": "Дата доставки не может быть раньше даты загрузки."})

    @property
    def age_minutes(self) -> int:
        base = self.refreshed_at or self.created_at
        return int((timezone.now() - base).total_seconds() // 60)

    def can_bump(self) -> bool:
        """Можно ли нажать 'Обновить' — не чаще, чем раз в 15 минут."""
        return self.age_minutes >= 15

    def bump(self):
        """
        Поднять объявление в выдаче (обновляет refreshed_at).
        Бросает ValidationError, если cooldown ещё не прошёл.
        """
        if not self.can_bump():
            raise ValidationError("Можно обновлять не чаще, чем раз в 15 минут.")
        self.refreshed_at = timezone.now()
        self.save(update_fields=["refreshed_at"])