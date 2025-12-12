from __future__ import annotations

from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

# from api.offers.models import Offer
from api.orders.models import Order
from api.loads.models import Cargo, CargoStatus


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

    # --- кто подтвердил условия ---
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
        indexes = [
            models.Index(fields=["status", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Agreement#{self.pk} offer={self.offer_id} status={self.status}"

    # ------------------------------------------------------------------
    # FACTORY
    # ------------------------------------------------------------------

    @classmethod
    def get_or_create_from_offer(cls, offer_id) -> "Agreement":
        """
        Создаёт соглашение при is_handshake.
        Повторно не создаётся.
        """
        # Локальный импорт, чтобы избежать циклического импорта
        from api.offers.models import Offer

        # Если передан ID, получаем объект Offer
        if isinstance(offer_id, int):
            offer = Offer.objects.get(id=offer_id)
        else:
            offer = offer_id

        agreement, created = cls.objects.get_or_create(
            offer=offer,
            defaults={
                "expires_at": timezone.now() + timedelta(minutes=30),
            },
        )
        return agreement

    # ------------------------------------------------------------------
    # ACCEPT / REJECT
    # ------------------------------------------------------------------

    def accept_by(self, user):
        if self.status != self.Status.PENDING:
            raise ValidationError("Соглашение уже неактивно.")

        offer = self.offer

        # CUSTOMER
        if user.role == "CUSTOMER" and user.id == offer.cargo.customer_id:
            self.accepted_by_customer = True

        # CARRIER
        elif user.role == "CARRIER" and user.id == offer.carrier_id:
            self.accepted_by_carrier = True

        # LOGISTIC
        elif user.role == "LOGISTIC" and (
            user.id == offer.logistic_id or user.id == offer.intermediary_id
        ):
            self.accepted_by_logistic = True

        else:
            raise ValidationError("Вы не участник данного соглашения.")

        self.save(
            update_fields=[
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "updated_at",
            ]
        )

        self.try_finalize()

    def reject(self, by_user=None):
        if self.status != self.Status.PENDING:
            return

        self.status = self.Status.CANCELLED
        self.save(update_fields=["status", "updated_at"])

        offer = self.offer
        offer.is_active = False
        offer.save(update_fields=["is_active"])

    # ------------------------------------------------------------------
    # FINALIZE
    # ------------------------------------------------------------------

    def try_finalize(self):
        """
        ЕДИНСТВЕННОЕ место, где может быть создан Order.
        """
        if self.status != self.Status.PENDING:
            return

        if timezone.now() > self.expires_at:
            self.expire()
            return

        offer = self.offer

        logistic_required = bool(offer.logistic or offer.intermediary)

        if not self.accepted_by_customer:
            return
        if not self.accepted_by_carrier:
            return
        if logistic_required and not self.accepted_by_logistic:
            return

        with transaction.atomic():
            cargo = (
                Cargo.objects.select_for_update()
                .only("id", "status", "assigned_carrier", "chosen_offer")
                .get(pk=offer.cargo_id)
            )

            if cargo.status == CargoStatus.MATCHED and cargo.chosen_offer_id:
                return

            order = Order.objects.create(
                cargo=cargo,
                customer=cargo.customer,
                carrier=offer.carrier,
                logistic=offer.intermediary or offer.logistic,
                created_by=offer.intermediary or offer.logistic or cargo.customer,
                offer=offer,
                status=Order.OrderStatus.NO_DRIVER,
                currency=offer.price_currency,
                price_total=offer.price_value or 0,
                route_distance_km=getattr(cargo, "route_km_cached", 0) or 0,
            )

            cargo.status = CargoStatus.MATCHED
            cargo.assigned_carrier = offer.carrier
            cargo.chosen_offer = offer
            cargo.save(update_fields=["status", "assigned_carrier", "chosen_offer"])

            offer.is_active = False
            offer.save(update_fields=["is_active"])

            self.status = self.Status.ACCEPTED
            self.save(update_fields=["status", "updated_at"])

    # ------------------------------------------------------------------
    # EXPIRE
    # ------------------------------------------------------------------

    def expire(self):
        if self.status != self.Status.PENDING:
            return

        self.status = self.Status.EXPIRED
        self.save(update_fields=["status", "updated_at"])

        offer = self.offer
        offer.is_active = False
        offer.save(update_fields=["is_active"])
