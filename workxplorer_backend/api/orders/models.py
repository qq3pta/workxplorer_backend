import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from api.loads.choices import Currency
from api.loads.models import Cargo
from api.notifications.services import notify
from api.payments.models import Payment


def order_upload_to(instance, filename: str) -> str:
    name = os.path.basename(filename or "")
    return f"orders/{instance.order_id}/{name}"


def validate_file_size(f):
    max_mb = 15
    if f.size > max_mb * 1024 * 1024:
        raise ValidationError(
            _("Максимальный размер файла — %(mb)s MB."),
            params={"mb": max_mb},
        )


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

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_created",
    )

    offer = models.OneToOneField(
        "offers.Offer", on_delete=models.SET_NULL, null=True, blank=True, related_name="order"
    )

    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    driver_status = models.CharField(
        max_length=20,
        choices=DriverStatus.choices,
        default=DriverStatus.EN_ROUTE,
    )

    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)

    price_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    route_distance_km = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    loading_datetime = models.DateTimeField(null=True, blank=True)
    unloading_datetime = models.DateTimeField(null=True, blank=True)

    invite_token = models.UUIDField(
        null=True, blank=True, unique=True, help_text="Токен приглашения перевозчика"
    )

    invited_carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invited_orders",
        help_text="Перевозчик, приглашённый вручную по ID",
    )

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
                check=models.Q(price_total__gte=0),
                name="order_price_total_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(route_distance_km__gte=0),
                name="order_route_km_gte_0",
            ),
        ]
        verbose_name = _("Заказ")
        verbose_name_plural = _("Заказы")

    def __str__(self) -> str:
        return f"Order#{self.pk} cargo={self.cargo_id} carrier={self.carrier_id or '—'}"

    def notify_created(self):
        payload = {"order_id": self.id}

        notify(
            user=self.customer,
            type="deal_success",
            title="Сделка успешно создана",
            message="Заказ успешно создан",
            payload=payload,
            cargo=self.cargo,
        )

        if self.carrier:
            notify(
                user=self.carrier,
                type="deal_success",
                title="Сделка успешно создана",
                message="Заказ успешно создан",
                payload=payload,
                cargo=self.cargo,
            )

    def notify_status_changed(self, old_status, new_status):
        payload = {
            "order_id": self.id,
            "old_status": old_status,
            "new_status": new_status,
        }

        if new_status == Order.OrderStatus.NO_DRIVER:
            for u in (self.customer, self.carrier):
                if u:
                    notify(
                        user=u,
                        type="driver_status_changed",
                        title="Статус водителя изменён",
                        message="У водителя возникла проблема или он отсутствует.",
                        payload=payload,
                        cargo=self.cargo,
                    )
            if not self.payments.exists():
                Payment.objects.create(
                    order=self,
                    amount=self.price_total,
                    currency=self.currency,
                    method="manual",
                )

            return

        if new_status == Order.OrderStatus.DELIVERED:
            for u in (self.customer, self.carrier):
                if u:
                    notify(
                        user=u,
                        type="payment_required",
                        title="Груз доставлен",
                        message="Перевозка завершена. Требуется подтверждение оплаты.",
                        payload=payload,
                        cargo=self.cargo,
                    )
            return

        if new_status == Order.OrderStatus.PAID:
            for u in (self.customer, self.carrier):
                if u:
                    notify(
                        user=u,
                        type="rating_required",
                        title="Оцените перевозку",
                        message="Оплата подтверждена. Пожалуйста, оставьте рейтинг.",
                        payload=payload,
                        cargo=self.cargo,
                    )
            return

        msg = f"Статус заказа обновлён: {old_status} → {new_status}"

        for u in (self.customer, self.carrier):
            if u:
                notify(
                    user=u,
                    type="cargo_status_changed",
                    title="Статус заказа изменён",
                    message=msg,
                    payload=payload,
                    cargo=self.cargo,
                )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None

        if not is_new:
            old_status = Order.objects.filter(pk=self.pk).values_list("status", flat=True).first()

        super().save(*args, **kwargs)

        if is_new:
            transaction.on_commit(lambda: self.notify_created())
            return

        if old_status and old_status != self.status:
            transaction.on_commit(
                lambda old=old_status, new=self.status: self.notify_status_changed(old, new)
            )

    def update_payment_status(self):
        """
        Обновляет статус заказа в зависимости от статусов всех платежей.
        Если все платежи завершены → заказ становится PAID.
        """
        payments = self.payments.all()

        if not payments.exists():
            return

        if all(p.status == "COMPLETED" for p in payments):
            old_status = self.status
            self.status = Order.OrderStatus.PAID
            self.save(update_fields=["status"])

            OrderStatusHistory.objects.create(
                order=self,
                old_status=old_status,
                new_status=self.status,
                user=None,
            )

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
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.OTHER)
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
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if not is_new:
            return

        def after_commit():
            if self.category == self.Category.LOADING:
                Order.objects.filter(id=self.order_id).update(loading_datetime=self.created_at)

            if self.category == self.Category.UNLOADING:
                Order.objects.filter(id=self.order_id).update(unloading_datetime=self.created_at)

            for u in (self.order.customer, self.order.carrier):
                if u:
                    notify(
                        user=u,
                        type="document_added",
                        title="Добавлен документ",
                        message=f"Добавлен документ: {self.get_category_display()}",
                        payload={"order_id": self.order.id, "document_id": self.id},
                        cargo=self.order.cargo,
                    )

        transaction.on_commit(after_commit)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Документ заказа")
        verbose_name_plural = _("Документы заказа")


class OrderStatusHistory(models.Model):
    """История изменений статуса заказа для таймлайна."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
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

    def __str__(self):
        return f"Order#{self.order_id}: {self.old_status} → {self.new_status}"
