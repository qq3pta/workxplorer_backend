from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from api.loads.models import Cargo, CargoStatus

# from api.offers.models import Offer
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
    def get_or_create_from_offer(cls, offer_id) -> Agreement:
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
            raise ValidationError("Соглашение уже обработано")

        offer = self.offer
        cargo = offer.cargo

        # 1️⃣ ЗАКАЗЧИК (НЕ СМОТРИМ НА РОЛЬ)
        if user.id == cargo.customer_id:
            self.accepted_by_customer = True

        # 2️⃣ ПЕРЕВОЗЧИК
        elif user.role == "CARRIER" and offer.carrier_id == user.id:
            self.accepted_by_carrier = True

        # 3️⃣ ЛОГИСТ (НЕ заказчик)
        elif user.role == "LOGISTIC":
            self.accepted_by_logistic = True

        else:
            raise PermissionDenied("Вы не участник соглашения")

        self.save(
            update_fields=[
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
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

        kind = offer.offer_kind()

        # CASE 1 и 2: есть перевозчик
        if kind in {"CUSTOMER_CARRIER", "LOGISTIC_CARRIER"}:
            if not (self.accepted_by_customer and self.accepted_by_carrier):
                return

        # CASE 3 и 4: перевозчика нет
        elif kind == "CUSTOMER_LOGISTIC":
            if not (self.accepted_by_customer and self.accepted_by_logistic):
                return

        else:
            return

        with transaction.atomic():
            cargo = (
                Cargo.objects.select_for_update()
                .only("id", "status", "assigned_carrier", "chosen_offer")
                .get(pk=offer.cargo_id)
            )

            if cargo.status == CargoStatus.MATCHED and cargo.chosen_offer_id:
                return

            Order.objects.create(
                cargo=cargo,
                customer=cargo.customer,
                carrier=offer.carrier if kind != "CUSTOMER_LOGISTIC" else None,
                logistic=offer.intermediary or offer.logistic,
                created_by=offer.intermediary or offer.logistic or cargo.customer,
                offer=offer,
                status=(
                    Order.OrderStatus.NO_DRIVER
                    if kind == "CUSTOMER_LOGISTIC"
                    else Order.OrderStatus.PENDING
                ),
                currency=offer.price_currency,
                price_total=offer.price_value or 0,
                route_distance_km=getattr(cargo, "route_km_cached", 0) or 0,
            )

            cargo.status = CargoStatus.MATCHED
            cargo.assigned_carrier = offer.carrier if kind != "CUSTOMER_LOGISTIC" else None
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
