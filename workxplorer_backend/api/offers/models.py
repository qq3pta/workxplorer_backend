from __future__ import annotations

from decimal import Decimal

from api.loads.choices import Currency
from api.loads.models import Cargo, CargoStatus
from django.apps import apps
from django.conf import settings
from django.core.exceptions import AppRegistryNotReady, PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, UniqueConstraint


class Offer(models.Model):
    class Initiator(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Заказчик"
        CARRIER = "CARRIER", "Перевозчик"

    # Привязки
    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        related_name="offers",
    )
    carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="offers",
    )

    # Содержимое оффера
    price_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    price_currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.UZS,
    )
    message = models.TextField(blank=True)

    # Согласования
    accepted_by_customer = models.BooleanField(default=False)
    accepted_by_carrier = models.BooleanField(default=False)
    initiator = models.CharField(
        max_length=16,
        choices=Initiator.choices,
        default=Initiator.CARRIER,
    )

    # Технические поля
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            UniqueConstraint(
                fields=["cargo", "carrier"],
                condition=Q(is_active=True),
                name="uniq_active_offer_per_carrier_per_cargo",
            ),
        ]
        indexes = [
            models.Index(fields=["cargo", "is_active"]),
            models.Index(fields=["carrier", "is_active"]),
            models.Index(fields=["initiator", "is_active"]),
        ]

    def __str__(self) -> str:
        return (
            f"Offer#{self.pk} cargo={self.cargo_id} carrier={self.carrier_id} by={self.initiator}"
        )

    # ---------------- Бизнес-логика ----------------

    @property
    def is_handshake(self) -> bool:
        """Есть взаимный акцепт обеих сторон."""
        return self.accepted_by_customer and self.accepted_by_carrier

    def make_counter(
        self,
        *,
        price_value: Decimal | None,
        price_currency: str | None = None,
        message: str | None = None,
        by_user=None,
    ) -> None:
        """
        Контр-предложение:
        - обновляет цену/валюту/сообщение (если заданы),
        - сбрасывает акцепты обеих сторон,
        - помечает инициатора шага,
        - оставляет оффер активным.
        """
        if price_value is not None:
            self.price_value = price_value
        if price_currency:
            self.price_currency = price_currency
        if message is not None:
            self.message = message

        if by_user is not None:
            self.initiator = (
                self.Initiator.CUSTOMER
                if by_user.id == self.cargo.customer_id
                else self.Initiator.CARRIER
            )

        self.accepted_by_customer = False
        self.accepted_by_carrier = False

        self.save(
            update_fields=[
                "price_value",
                "price_currency",
                "message",
                "initiator",
                "accepted_by_customer",
                "accepted_by_carrier",
                "updated_at",
            ]
        )

    def _finalize_handshake(self, cargo_locked: Cargo | None = None) -> None:
        """
        Эффекты взаимного согласия (выполнять ТОЛЬКО внутри transaction.atomic).
        Если передан cargo_locked — считаем, что строка уже взята под select_for_update().
        """
        cargo = cargo_locked or self.cargo

        cargo.status = CargoStatus.MATCHED

        if hasattr(cargo, "assigned_carrier_id"):
            cargo.assigned_carrier_id = self.carrier_id
        if hasattr(cargo, "chosen_offer_id"):
            cargo.chosen_offer_id = self.id

        update_fields = ["status"]
        if hasattr(cargo, "assigned_carrier_id"):
            update_fields.append("assigned_carrier")
        if hasattr(cargo, "chosen_offer_id"):
            update_fields.append("chosen_offer")

        cargo.save(update_fields=update_fields)

        Offer.objects.filter(cargo_id=cargo.id, is_active=True).exclude(pk=self.pk).update(
            is_active=False
        )

        try:
            Order = apps.get_model("orders", "Order")
        except (LookupError, AppRegistryNotReady):
            return

        route_km = (
            getattr(cargo, "route_distance_km", None)
            or getattr(cargo, "route_km_cached", None)
            or getattr(cargo, "route_km", None)
            or getattr(cargo, "path_km", None)
            or 0
        )

        Order.objects.get_or_create(
            cargo=cargo,
            defaults={
                "customer_id": cargo.customer_id,
                "carrier_id": self.carrier_id,
                "currency": self.price_currency
                or getattr(cargo, "price_currency", None)
                or Currency.UZS,
                "price_total": self.price_value or Decimal("0"),
                "route_distance_km": route_km,
            },
        )

    def accept_by(self, user) -> None:
        """
        Акцепт со стороны клиента (владельца груза) или перевозчика.
        Разрешено только участникам и только для активного оффера.
        При взаимном согласии — атомарно фиксирует сделку (_finalize_handshake).
        """
        if not self.is_active:
            raise ValidationError("Нельзя принять неактивный оффер.")

        if user.id == self.cargo.customer_id:
            if not self.accepted_by_customer:
                self.accepted_by_customer = True
        elif user.id == self.carrier_id:
            if not self.accepted_by_carrier:
                self.accepted_by_carrier = True
        else:
            raise PermissionDenied("Нельзя принять оффер: вы не участник сделки.")

        with transaction.atomic():
            self.save(update_fields=["accepted_by_customer", "accepted_by_carrier", "updated_at"])

            if self.is_handshake:
                cargo_locked = (
                    Cargo.objects.select_for_update()
                    .only("id", "status", "assigned_carrier", "chosen_offer")
                    .get(pk=self.cargo_id)
                )

                # Если уже кем-то зафиксирован матч с выбранным оффером — выходим
                if cargo_locked.status == CargoStatus.MATCHED and getattr(
                    cargo_locked, "chosen_offer_id", None
                ):
                    return

                self._finalize_handshake(cargo_locked=cargo_locked)

    def reject_by(self, user) -> None:
        """
        Отклонение со стороны любой из сторон — оффер деактивируется.
        Разрешено только участникам сделки.
        """
        if user.id not in (self.cargo.customer_id, self.carrier_id):
            raise PermissionDenied("Нельзя отклонить оффер: вы не участник сделки.")

        if self.is_active:
            self.is_active = False
            self.save(update_fields=["is_active", "updated_at"])
