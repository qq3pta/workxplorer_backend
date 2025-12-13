from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import models, transaction
from django.utils import timezone

from api.loads.models import Cargo, CargoStatus
from api.orders.models import Order


class Agreement(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает подтверждения"
        ACCEPTED = "accepted", "Принято"
        EXPIRED = "expired", "Истекло"
        CANCELLED = "cancelled", "Отменено"

    offer = models.OneToOneField(
        "offers.Offer",
        on_delete=models.CASCADE,
        related_name="agreement",
    )

    accepted_by_customer = models.BooleanField(default=False)
    accepted_by_carrier = models.BooleanField(default=False)
    accepted_by_logistic = models.BooleanField(default=False)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    # --------------------------------------------------
    # FACTORY
    # --------------------------------------------------

    @classmethod
    def get_or_create_from_offer(cls, offer):
        agreement, _ = cls.objects.get_or_create(
            offer=offer,
            defaults={
                "expires_at": timezone.now() + timedelta(minutes=30),
            },
        )
        return agreement

    # --------------------------------------------------
    # ACCEPT
    # --------------------------------------------------

    def accept_by(self, user):
        if self.status != self.Status.PENDING:
            raise ValidationError("Соглашение уже обработано")

        offer = self.offer
        cargo = offer.cargo
        accepted_as_participant = False

        if user.role == "CUSTOMER":
            if user.id in (cargo.customer_id, cargo.created_by_id):
                self.accepted_by_customer = True
                accepted_as_participant = True

        elif user.role == "CARRIER" and user.id == offer.carrier_id:
            self.accepted_by_carrier = True
            accepted_as_participant = True

        elif user.role == "LOGISTIC" and user.id in (
            offer.logistic_id,
            offer.intermediary_id,
        ):
            self.accepted_by_logistic = True
            accepted_as_participant = True

        if not accepted_as_participant:
            raise PermissionDenied("Вы не участник соглашения или не имеете прав на акцепт.")

        self.save()
        self.try_finalize()

    # --------------------------------------------------
    # FINALIZE
    # --------------------------------------------------

    def try_finalize(self):
        if self.status != self.Status.PENDING:
            return

        if timezone.now() > self.expires_at:
            self.expire()
            return

        offer = self.offer
        kind = offer.deal_type  # строка

        if kind in {"customer_carrier", "logistic_carrier"}:
            if not (self.accepted_by_customer and self.accepted_by_carrier):
                return

        elif kind == "customer_logistic":
            if not (self.accepted_by_customer and self.accepted_by_logistic):
                return

        elif kind == "logistic_logistic":
            if not self.accepted_by_logistic:
                return

        else:
            return

        with transaction.atomic():
            cargo = Cargo.objects.select_for_update().get(pk=offer.cargo_id)

            if cargo.status == CargoStatus.MATCHED:
                return

            Order.objects.create(
                cargo=cargo,
                customer=cargo.customer,
                carrier=offer.carrier if kind != "customer_logistic" else None,
                logistic=offer.intermediary or offer.logistic,
                created_by=offer.intermediary or offer.logistic or cargo.customer,
                offer=offer,
                status=(
                    Order.OrderStatus.NO_DRIVER
                    if kind == "customer_logistic"
                    else Order.OrderStatus.PENDING
                ),
                currency=offer.price_currency,
                price_total=offer.price_value or 0,
            )

            cargo.status = CargoStatus.MATCHED
            cargo.assigned_carrier = offer.carrier if kind != "customer_logistic" else None
            cargo.chosen_offer = offer
            cargo.save()

            offer.is_active = False
            offer.save()

            self.status = self.Status.ACCEPTED
            self.save()

    # --------------------------------------------------
    # EXPIRE
    # --------------------------------------------------

    def expire(self):
        if self.status != self.Status.PENDING:
            return

        self.status = self.Status.EXPIRED
        self.save()

        self.offer.is_active = False
        self.offer.save()
