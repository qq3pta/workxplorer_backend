import uuid

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.manager import Manager as DjangoManager
from django.utils import timezone

from .choices import ContactPref, Currency, ModerationStatus, TransportType


class CargoStatus(models.TextChoices):
    POSTED = "POSTED", "Опубликована"
    MATCHED = "MATCHED", "В работе"
    DELIVERED = "DELIVERED", "Доставлено"
    COMPLETED = "COMPLETED", "Завершено"
    CANCELLED = "CANCELLED", "Отменена"


class Cargo(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cargos",
        verbose_name="Заказчик",
    )
    product = models.CharField("Название груза", max_length=120)
    description = models.TextField("Описание", blank=True)
    origin_country = models.CharField(max_length=100, default="", blank=True)
    origin_address = models.CharField(max_length=255)
    origin_city = models.CharField(max_length=100)
    destination_country = models.CharField(max_length=100, default="", blank=True)
    destination_address = models.CharField(max_length=255)
    destination_city = models.CharField(max_length=100)
    origin_point = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)
    dest_point = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)
    load_date = models.DateField("Дата загрузки")
    delivery_date = models.DateField("Дата доставки", null=True, blank=True)
    transport_type = models.CharField(max_length=10, choices=TransportType.choices)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=2)
    price_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    price_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    price_uzs = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Цена в сумах"
    )
    contact_pref = models.CharField(max_length=10, choices=ContactPref.choices)
    is_hidden = models.BooleanField(default=False)
    moderation_status = models.CharField(
        max_length=10,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
    )
    refreshed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=CargoStatus.choices, default=CargoStatus.POSTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_cargos",
        verbose_name="Назначенный перевозчик",
    )
    chosen_offer = models.ForeignKey(
        "offers.Offer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chosen_for",
        verbose_name="Выбранное предложение",
    )
    route_km_cached = models.FloatField(null=True, blank=True)
    route_duration_min_cached = models.FloatField(null=True, blank=True)

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
        if self.delivery_date and self.load_date and self.delivery_date < self.load_date:
            raise ValidationError(
                {"delivery_date": "Дата доставки не может быть раньше даты загрузки."}
            )

    @property
    def age_minutes(self) -> int:
        base = self.refreshed_at or self.created_at
        return int((timezone.now() - base).total_seconds() // 60)

    def can_bump(self) -> bool:
        """Можно нажать 'Обновить' — не чаще, чем раз в 15 минут."""
        return self.age_minutes >= 15

    def bump(self):
        if not self.can_bump():
            raise ValidationError("Можно обновлять не чаще, чем раз в 15 минут.")
        self.refreshed_at = timezone.now()
        self.save(update_fields=["refreshed_at"])

    def update_route_cache(self, save: bool = True) -> float | None:
        try:
            if self.origin_point and self.dest_point:
                from api.routing.services import get_route

                rc = get_route(self.origin_point, self.dest_point)
                if rc:
                    self.route_km_cached = float(rc.distance_km)
                    self.route_duration_min_cached = (
                        float(rc.duration_min) if rc.duration_min else None
                    )
                    if save:
                        self.save(update_fields=["route_km_cached", "route_duration_min_cached"])
                    return self.route_km_cached
        except Exception:
            return None
        return None

    def update_price_uzs(self):
        """Конвертирует цену в сумах при создании груза."""
        try:
            from api.common.utils import convert_to_uzs

            if self.price_value and self.price_currency:
                self.price_uzs = convert_to_uzs(self.price_value, self.price_currency)
                self.save(update_fields=["price_uzs"])
        except Exception:
            return None
