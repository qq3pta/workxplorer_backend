import secrets
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.manager import Manager as DjangoManager
from django.utils import timezone
from unidecode import unidecode

from api.notifications.services import notify

from .choices import ContactPref, Currency, ModerationStatus, TransportType


class CargoStatus(models.TextChoices):
    POSTED = "POSTED", "Опубликована"
    MATCHED = "MATCHED", "В работе"
    DELIVERED = "DELIVERED", "Доставлено"
    COMPLETED = "COMPLETED", "Завершено"
    CANCELLED = "CANCELLED", "Отменена"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Наличные"
    CASHLESS = "cashless", "Безналичный расчёт"
    BOTH = "both", "Наличные + безналичный расчёт"


class Cargo(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cargos",
        verbose_name="Заказчик",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cargos_created",
        verbose_name="Создано логистом",
    )

    product = models.CharField("Название груза", max_length=120)
    description = models.TextField("Описание", blank=True)
    origin_country = models.CharField(max_length=100, default="", blank=True)
    origin_address = models.CharField(max_length=255)
    origin_city = models.CharField(max_length=100)
    origin_city_latin = models.CharField(max_length=120, blank=True, null=True)
    destination_country = models.CharField(max_length=100, default="", blank=True)
    destination_address = models.CharField(max_length=255)
    destination_city = models.CharField(max_length=100)
    destination_city_latin = models.CharField(max_length=120, blank=True, null=True)
    origin_point = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)
    dest_point = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)
    load_date = models.DateField("Дата загрузки")
    delivery_date = models.DateField("Дата доставки", null=True, blank=True)
    transport_type = models.CharField(max_length=10, choices=TransportType.choices)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=2)
    axles = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(3), MaxValueValidator(10)],
        help_text="Количество осей (3–10)",
    )
    volume_m3 = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Объём, м³",
    )

    price_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    price_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    price_uzs = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Цена в сумах"
    )

    contact_pref = models.CharField(max_length=10, choices=ContactPref.choices)

    is_hidden = models.BooleanField(
        default=False,
        verbose_name="Скрыта от других пользователей",
    )

    moderation_status = models.CharField(
        max_length=10,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    status = models.CharField(
        max_length=20, choices=CargoStatus.choices, default=CargoStatus.POSTED
    )
    refreshed_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        verbose_name="Способ оплаты",
    )

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
            models.Index(fields=["origin_city_latin"]),
            models.Index(fields=["destination_city_latin"]),
            models.Index(fields=["status"]),
            models.Index(fields=["refreshed_at"]),
            models.Index(fields=["price_value"]),
            models.Index(fields=["price_currency"]),
            models.Index(fields=["axles"]),
            models.Index(fields=["volume_m3"]),
        ]

    def __str__(self):
        return f"{self.product} ({self.origin_city} → {self.destination_city})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        old_moderation = None
        old_status = None

        if not is_new:
            try:
                old = Cargo.objects.get(pk=self.pk)
                old_moderation = old.moderation_status
                old_status = old.status
            except Cargo.DoesNotExist:
                pass

        if self.origin_city:
            self.origin_city_latin = unidecode(self.origin_city).lower()

        if self.destination_city:
            self.destination_city_latin = unidecode(self.destination_city).lower()

        super().save(*args, **kwargs)

        if is_new:
            if self.moderation_status == ModerationStatus.APPROVED:
                notify(
                    user=self.customer,
                    type="order_published",
                    title="Заявка опубликована",
                    message="Ваша заявка сразу опубликована",
                    cargo=self,
                    payload={"cargo_id": self.id},
                )
            else:
                notify(
                    user=self.customer,
                    type="order_created",
                    title="Заявка успешно создана",
                    message="Ваша заявка создана и отправлена на модерацию",
                    cargo=self,
                    payload={"cargo_id": self.id},
                )
            return

        if old_moderation != self.moderation_status:
            # публикация
            if self.moderation_status == ModerationStatus.APPROVED:
                notify(
                    user=self.customer,
                    type="order_published",
                    title="Заявка опубликована",
                    message="Ваша заявка прошла модерацию",
                    cargo=self,
                    payload={"cargo_id": self.id},
                )

            elif self.moderation_status == ModerationStatus.REJECTED:
                notify(
                    user=self.customer,
                    type="order_rejected",
                    title="Заявка отклонена",
                    message="Модерация не пройдена",
                    cargo=self,
                    payload={"cargo_id": self.id},
                )

        if old_status != self.status:
            notify(
                user=self.customer,
                type="cargo_status_changed",
                title="Статус перевозки изменён",
                message=f"Статус изменён: {self.get_status_display()}",
                cargo=self,
                payload={"cargo_id": self.id},
            )

    @property
    def weight_tons(self):
        try:
            return (Decimal(self.weight_kg) / Decimal("1000")).quantize(Decimal("0.0001"))
        except Exception:
            return None

    @weight_tons.setter
    def weight_tons(self, value):
        if value is None:
            self.weight_kg = None
        else:
            self.weight_kg = (Decimal(str(value)) * Decimal("1000")).quantize(Decimal("0.01"))

    def clean(self):
        if self.delivery_date and self.load_date and self.delivery_date < self.load_date:
            raise ValidationError(
                {"delivery_date": "Дата доставки не может быть раньше даты загрузки."}
            )
        if self.axles is not None and not (3 <= self.axles <= 10):
            raise ValidationError({"axles": "Оси должны быть в диапазоне 3–10."})
        if self.volume_m3 is not None and self.volume_m3 <= 0:
            raise ValidationError({"volume_m3": "Объём должен быть больше нуля."})

    @property
    def age_minutes(self) -> int:
        base = self.refreshed_at or self.created_at
        return int((timezone.now() - base).total_seconds() // 60)

    def can_bump(self) -> bool:
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
        try:
            from common.utils import convert_to_uzs

            if self.price_value and self.price_currency:
                self.price_uzs = convert_to_uzs(self.price_value, self.price_currency)
                self.save(update_fields=["price_uzs"])
        except Exception:
            return None


def invite_expiry():
    return timezone.now() + timedelta(days=3)


class LoadInvite(models.Model):
    load = models.ForeignKey("loads.Cargo", on_delete=models.CASCADE, related_name="invites")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invites_created",
    )

    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(default=invite_expiry)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)
