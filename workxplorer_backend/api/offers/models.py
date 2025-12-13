from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, UniqueConstraint

from api.loads.choices import Currency
from api.loads.models import Cargo
from api.notifications.services import notify

# from api.loads.models import Cargo, CargoStatus
# from api.orders.models import Order


class Offer(models.Model):
    class Initiator(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Заказчик"
        CARRIER = "CARRIER", "Перевозчик"
        LOGISTIC = "LOGISTIC", "Логист"

    class DealType(models.TextChoices):
        CUSTOMER_CARRIER = "customer_carrier"
        LOGISTIC_CARRIER = "logistic_carrier"
        CUSTOMER_LOGISTIC = "customer_logistic"
        LOGISTIC_LOGISTIC = "logistic_logistic"

    deal_type = models.CharField(
        max_length=32,
        choices=DealType.choices,
    )

    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        related_name="offers",
    )

    logistic = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logistic_offers",
        limit_choices_to={"role": "LOGISTIC"},
    )

    intermediary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="intermediary_offers",
        limit_choices_to={"role": "LOGISTIC"},
    )

    carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="offers",
        limit_choices_to={"role": "CARRIER"},
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
    accepted_by_logistic = models.BooleanField(default=False)
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
        kind = self.deal_type
        if kind in {self.DealType.CUSTOMER_CARRIER, self.DealType.LOGISTIC_CARRIER}:
            return self.accepted_by_customer and self.accepted_by_carrier
        if kind in {self.DealType.CUSTOMER_LOGISTIC, self.DealType.LOGISTIC_LOGISTIC}:
            return self.accepted_by_customer and self.accepted_by_logistic
        return False

    # ---------------- Notifications ----------------
    def send_create_notifications(self):
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

    # ---------------- Reject ----------------
    def reject_by(self, user):
        role = getattr(user, "role", None)
        if not self.is_active:
            raise ValidationError("Оффер уже неактивен.")
        if role == "CUSTOMER" and user.id == self.cargo.customer_id:
            self.is_active = False
            self.accepted_by_customer = False
        elif role == "CARRIER" and user.id == self.carrier_id:
            self.is_active = False
            self.accepted_by_carrier = False
        elif role == "LOGISTIC" and user.id in (self.logistic_id, self.intermediary_id):
            self.is_active = False
            self.accepted_by_logistic = False
        else:
            raise PermissionDenied("Вы не можете отклонить этот оффер.")
        self.save(
            update_fields=[
                "is_active",
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "updated_at",
            ]
        )
        self.send_reject_notifications(user)

    # ---------------- Make Counter ----------------
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
            if by_user.role == "LOGISTIC":
                self.initiator = self.Initiator.LOGISTIC
            elif by_user.id == self.cargo.customer_id:
                self.initiator = self.Initiator.CUSTOMER
            else:
                self.initiator = self.Initiator.CARRIER
        self.accepted_by_customer = False
        self.accepted_by_carrier = False
        self.accepted_by_logistic = False
        self.save(
            update_fields=[
                "price_value",
                "price_currency",
                "message",
                "initiator",
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "updated_at",
            ]
        )
        self.send_counter_notifications(by_user)

    @staticmethod
    def resolve_deal_type(*, initiator_user, carrier=None, logistic=None) -> str:
        role = getattr(initiator_user, "role", None)

        # Перевозчик → всегда заказчику
        if role == "CARRIER":
            return Offer.DealType.CUSTOMER_CARRIER

        # Заказчик
        if role == "CUSTOMER":
            if logistic and not carrier:
                return Offer.DealType.CUSTOMER_LOGISTIC
            return Offer.DealType.CUSTOMER_CARRIER

        # Логист
        if role == "LOGISTIC":
            if carrier:
                return Offer.DealType.LOGISTIC_CARRIER
            return Offer.DealType.CUSTOMER_LOGISTIC

        raise ValidationError("Невозможно определить тип сделки")

    # ---------------- Accept Dispatcher ----------------
    def accept_by(self, user) -> None:
        if not self.is_active:
            raise ValidationError("Нельзя принять неактивный оффер.")

        handlers = {
            self.DealType.CUSTOMER_CARRIER: self._accept_case_customer_carrier,
            self.DealType.LOGISTIC_CARRIER: self._accept_case_logistic_carrier,
            self.DealType.CUSTOMER_LOGISTIC: self._accept_case_customer_logistic,
            self.DealType.LOGISTIC_LOGISTIC: self._accept_case_logistic_logistic,
        }
        handler = handlers.get(self.deal_type)
        if not handler:
            raise ValidationError("Неизвестный тип сделки")
        handler(user)

    # ---------------- CASES ----------------
    def _accept_case_customer_carrier(self, user):
        cargo = self.cargo
        if user.id in (cargo.customer_id, cargo.created_by_id):
            self.accepted_by_customer = True
        elif user.role == "CARRIER" and user.id == self.carrier_id:
            self.accepted_by_carrier = True
        else:
            raise PermissionDenied("Недопустимый участник для данного кейса")
        with transaction.atomic():
            self.save(update_fields=["accepted_by_customer", "accepted_by_carrier", "updated_at"])
            self.send_accept_notifications(user)
            if self.accepted_by_customer and self.accepted_by_carrier:
                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)

    def _accept_case_logistic_carrier(self, user):
        if user.role == "LOGISTIC":
            if user.id in (self.logistic_id, self.intermediary_id):
                self.accepted_by_logistic = True
            elif self.intermediary is None:
                self.accepted_by_logistic = True
                self.intermediary = user
            else:
                raise PermissionDenied("Логист не является участником этого оффера")
        elif user.role == "CARRIER" and user.id == self.carrier_id:
            self.accepted_by_carrier = True
        else:
            raise PermissionDenied("Недопустимый участник для данного кейса")
        with transaction.atomic():
            self.save(
                update_fields=[
                    "accepted_by_logistic",
                    "accepted_by_carrier",
                    "intermediary",
                    "updated_at",
                ]
            )
            self.send_accept_notifications(user)
            if self.accepted_by_logistic and self.accepted_by_carrier:
                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)

    def _accept_case_customer_logistic(self, user):
        cargo = self.cargo
        if user.id in (cargo.customer_id, cargo.created_by_id):
            self.accepted_by_customer = True
        elif user.role == "LOGISTIC":
            if user.id in (self.logistic_id, self.intermediary_id):
                self.accepted_by_logistic = True
            elif self.intermediary is None:
                self.accepted_by_logistic = True
                self.intermediary = user
            else:
                raise PermissionDenied("Логист не является участником этого оффера")
        else:
            raise PermissionDenied("Недопустимый участник для данного кейса")
        with transaction.atomic():
            self.save(
                update_fields=[
                    "accepted_by_customer",
                    "accepted_by_logistic",
                    "intermediary",
                    "updated_at",
                ]
            )
            self.send_accept_notifications(user)
            if self.accepted_by_customer and self.accepted_by_logistic:
                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)

    def _accept_case_logistic_logistic(self, user):
        if user.role == "LOGISTIC":
            if user.id in (self.logistic_id, self.intermediary_id):
                self.accepted_by_logistic = True
            elif self.intermediary is None:
                self.accepted_by_logistic = True
                self.intermediary = user
            else:
                raise PermissionDenied("Логист не является участником этого оффера")
        else:
            raise PermissionDenied("Недопустимый участник для данного кейса")
        with transaction.atomic():
            self.save(update_fields=["accepted_by_logistic", "intermediary", "updated_at"])
            self.send_accept_notifications(user)
            if self.accepted_by_customer and self.accepted_by_logistic:
                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)
