import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from api.loads.choices import Currency
from api.loads.models import Cargo


def order_upload_to(instance, filename: str) -> str:
    name = os.path.basename(filename or "")
    return f"orders/{instance.order_id}/{name}"


def validate_file_size(f):
    max_mb = 15
    if f.size > max_mb * 1024 * 1024:
        raise ValidationError(_("Максимальный размер файла — %(mb)s MB."), params={"mb": max_mb})


class Order(models.Model):
    class OrderStatus(models.TextChoices):
        PENDING = "pending", _("В ожидании")
        EN_ROUTE = "in_process", _("В процессе")
        DELIVERED = "delivered", _("Доставлен")
        NO_DRIVER = "no_driver", _("Без водителя")
        PAID = "paid", _("Оплачено")

    class DriverStatus(models.TextChoices):
        STOPPED = "stopped", _("Остановился")
        EN_ROUTE = "en_route", _("В пути")
        PROBLEM = "problem", _("Проблема")

    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE, related_name="orders")

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders_as_customer",
    )
    carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_as_carrier",
    )

    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING
    )
    driver_status = models.CharField(
        max_length=20, choices=DriverStatus.choices, default=DriverStatus.EN_ROUTE
    )
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)

    price_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    route_distance_km = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    loading_datetime = models.DateTimeField(null=True, blank=True)
    unloading_datetime = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["cargo", "status"], name="order_cargo_status_idx"),
            models.Index(fields=["customer", "status"], name="order_customer_status_idx"),
            models.Index(fields=["carrier", "status"], name="order_carrier_status_idx"),
            models.Index(fields=["created_at"], name="order_created_idx"),
            models.Index(fields=["status"], name="order_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["cargo"], name="uniq_order_per_cargo"),
            models.CheckConstraint(
                check=models.Q(price_total__gte=0), name="order_price_total_gte_0"
            ),
            models.CheckConstraint(
                check=models.Q(route_distance_km__gte=0), name="order_route_km_gte_0"
            ),
        ]
        verbose_name = _("Заказ")
        verbose_name_plural = _("Заказы")

    def __str__(self) -> str:
        return f"Order#{self.pk} cargo={self.cargo_id} carrier={self.carrier_id or '—'}"

    @property
    def price_per_km(self) -> float:
        d = float(self.route_distance_km or 0)
        return float(self.price_total or 0) / d if d > 0 else 0.0


class OrderDocument(models.Model):
    class Category(models.TextChoices):
        LICENSES = "licenses", "Лицензии"
        CONTRACTS = "contracts", "Договора"
        LOADING = "loading", "Документы о погрузке"
        UNLOADING = "unloading", "Документы о разгрузке"
        OTHER = "other", "Дополнительно"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="documents")

    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OTHER,
    )

    title = models.CharField(max_length=255, blank=True)

    file = models.FileField(
        upload_to=order_upload_to,
        validators=[
            FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png", "doc", "docx"]),
            validate_file_size,
        ],
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or f"Document#{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if self.category == self.Category.LOADING:
            self.order.loading_datetime = self.created_at
            self.order.save(update_fields=["loading_datetime"])

        if self.category == self.Category.UNLOADING:
            self.order.unloading_datetime = self.created_at
            self.order.save(update_fields=["unloading_datetime"])

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Документ заказа")
        verbose_name_plural = _("Документы заказа")
        indexes = [
            models.Index(fields=["order"], name="orderdoc_order_idx"),
            models.Index(fields=["created_at"], name="orderdoc_created_idx"),
            models.Index(fields=["uploaded_by"], name="orderdoc_uploader_idx"),
            models.Index(fields=["category"], name="orderdoc_category_idx"),
        ]


class OrderStatusHistory(models.Model):
    """
    История изменений статуса заказа для таймлайна на вкладке «Статусы».
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    old_status = models.CharField(
        max_length=20,
        choices=Order.OrderStatus.choices,
        blank=True,
        null=True,
    )
    new_status = models.CharField(
        max_length=20,
        choices=Order.OrderStatus.choices,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_changes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Изменение статуса заказа")
        verbose_name_plural = _("История статусов заказов")
        indexes = [
            models.Index(fields=["order"], name="orderstatus_order_idx"),
            models.Index(fields=["created_at"], name="orderstatus_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Order#{self.order_id}: {self.old_status} → {self.new_status}"
