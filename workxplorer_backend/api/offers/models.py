from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, UniqueConstraint

from api.loads.choices import Currency
from api.loads.models import Cargo, CargoStatus
from api.orders.models import Order
from api.notifications.services import notify


class Offer(models.Model):
    class Initiator(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Заказчик"
        CARRIER = "CARRIER", "Перевозчик"

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

    accepted_by_customer = models.BooleanField(default=False)
    accepted_by_carrier = models.BooleanField(default=False)
    initiator = models.CharField(
        max_length=16,
        choices=Initiator.choices,
        default=Initiator.CARRIER,
    )

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

    @property
    def is_handshake(self) -> bool:
        return self.accepted_by_customer and self.accepted_by_carrier

    def send_create_notifications(self):
        """Вызывается вручную из create() сериализатора."""
        customer = self.cargo.customer
        carrier = self.carrier

        notify(
            user=carrier,
            type="offer_sent",
            title="Предложение отправлено",
            message="Вы отправили предложение заказчику.",
            offer=self,
            cargo=self.cargo,
        )

        notify(
            user=customer,
            type="offer_received_from_carrier",
            title="Новое предложение",
            message="Вы получили предложение от перевозчика.",
            offer=self,
            cargo=self.cargo,
        )

    def send_invite_notifications(self):
        customer = self.cargo.customer
        carrier = self.carrier

        notify(
            user=customer,
            type="offer_sent",
            title="Инвайт отправлен",
            message="Вы отправили предложение перевозчику.",
            offer=self,
            cargo=self.cargo,
        )

        notify(
            user=carrier,
            type="offer_from_customer",
            title="Новое предложение от заказчика",
            message="Заказчик отправил вам предложение.",
            offer=self,
            cargo=self.cargo,
        )

    def send_counter_notifications(self, by_user):
        customer = self.cargo.customer
        carrier = self.carrier

        notify(
            user=by_user,
            type="offer_my_response_sent",
            title="Ответ отправлен",
            message="Вы предложили новые условия.",
            offer=self,
            cargo=self.cargo,
        )

        other = customer if by_user.id == carrier.id else carrier

        notify(
            user=other,
            type="offer_response_to_me",
            title="Получен ответ по предложению",
            message="По предложению поступил новый ответ.",
            offer=self,
            cargo=self.cargo,
        )

    def send_accept_notifications(self, accepted_by):
        customer = self.cargo.customer
        carrier = self.carrier

        if self.is_handshake:
            notify(
                user=customer,
                type="deal_success",
                title="Сделка подтверждена",
                message="Перевозчик подтвердил сделку.",
                offer=self,
                cargo=self.cargo,
            )
            notify(
                user=carrier,
                type="deal_success",
                title="Сделка подтверждена",
                message="Заказчик подтвердил сделку.",
                offer=self,
                cargo=self.cargo,
            )
            return

        other = customer if accepted_by.id == carrier.id else carrier

        notify(
            user=other,
            type="deal_confirm_required_by_other",
            title="Необходима подтвердить сделку",
            message="Другая сторона приняла предложение. Подтвердите сделку.",
            offer=self,
            cargo=self.cargo,
        )

    def send_reject_notifications(self, rejected_by):
        customer = self.cargo.customer
        carrier = self.carrier

        other = customer if rejected_by.id == carrier.id else carrier

        notify(
            user=other,
            type="deal_rejected_by_other",
            title="Предложение отклонено",
            message="Другая сторона отклонила предложение.",
            offer=self,
            cargo=self.cargo,
        )

    def make_counter(
        self,
        *,
        price_value: Decimal | None,
        price_currency: str | None = None,
        message: str | None = None,
        by_user=None,
    ) -> None:
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

        self.send_counter_notifications(by_user)

    def accept_by(self, user) -> None:
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
            self.send_accept_notifications(user)

            if self.is_handshake:
                cargo_locked = (
                    Cargo.objects.select_for_update()
                    .only("id", "status", "assigned_carrier", "chosen_offer")
                    .get(pk=self.cargo_id)
                )

                if cargo_locked.status == CargoStatus.MATCHED and getattr(
                    cargo_locked, "chosen_offer_id", None
                ):
                    return

                self._finalize_handshake(cargo_locked=cargo_locked)

    # ---------------- FINALIZE HANDSHAKE --------------------

    def _finalize_handshake(self, *, cargo_locked):
        """
        Завершает handshake:
        - меняет статус груза на MATCHED
        - назначает перевозчика
        - сохраняет выбранный оффер
        - создаёт заказ
        """

        cargo_locked.status = CargoStatus.MATCHED
        cargo_locked.assigned_carrier_id = self.carrier_id
        cargo_locked.chosen_offer_id = self.id

        cargo_locked.save(update_fields=["status", "assigned_carrier_id", "chosen_offer_id"])

        Order.objects.create(
            cargo=cargo_locked,
            carrier=self.carrier,
            offer=self,
        )

    def reject_by(self, user) -> None:
        if user.id not in (self.cargo.customer_id, self.carrier_id):
            raise PermissionDenied("Нельзя отклонить оффер: вы не участник сделки.")

        if self.is_active:
            self.is_active = False
            self.save(update_fields=["is_active", "updated_at"])

            self.send_reject_notifications(user)
