from api.loads.choices import Currency
from api.loads.models import Cargo, CargoStatus
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import Q, UniqueConstraint


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

    price_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    price_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    message = models.TextField(blank=True)

    # согласия сторон
    accepted_by_customer = models.BooleanField(default=False)
    accepted_by_carrier = models.BooleanField(default=False)

    # кто создал предложение (для разделения «я предложил» / «предложили мне»)
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
            # Разрешаем сколько угодно НЕактивных офферов,
            # но только ОДИН активный на пару (cargo, carrier)
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

    def __str__(self):
        return f"Offer#{self.pk} cargo={self.cargo_id} carrier={self.carrier_id} by={self.initiator}"

    # ---------------- Бизнес-логика ----------------

    def make_counter(self, *, price_value, price_currency=None, message=None):
        """
        Контр-предложение:
        - обновляет price_value/price_currency/message (если заданы),
        - сбрасывает акцепты обеих сторон,
        - оставляет оффер активным.
        """
        if price_value is not None:
            self.price_value = price_value
        if price_currency:
            self.price_currency = price_currency
        if message is not None:
            self.message = message

        self.accepted_by_customer = False
        self.accepted_by_carrier = False

        self.save(
            update_fields=[
                "price_value",
                "price_currency",
                "message",
                "accepted_by_customer",
                "accepted_by_carrier",
                "updated_at",
            ]
        )

    @property
    def is_handshake(self) -> bool:
        return self.accepted_by_customer and self.accepted_by_carrier

    def _finalize_handshake(self):
        """
        Применяет эффекты взаимного согласия:
        - cargo.status = MATCHED
        - cargo.assigned_carrier = self.carrier (если поле существует)
        - cargo.chosen_offer = self (если поле существует)
        - все прочие офферы по грузу → is_active=False
        Предполагается вызов внутри transaction.atomic() и после select_for_update() по Cargo.
        """
        cargo = self.cargo

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

        Offer.objects.filter(cargo_id=cargo.id).exclude(pk=self.pk).update(is_active=False)

    def accept_by(self, user):
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
                cargo = (
                    Cargo.objects.select_for_update()
                    .only("id", "status", "assigned_carrier", "chosen_offer")
                    .get(pk=self.cargo_id)
                )

                if cargo.status == CargoStatus.MATCHED and getattr(cargo, "chosen_offer_id", None):
                    return

                self._finalize_handshake()

    def reject_by(self, user):
        """
        Отклонение со стороны любой из сторон — оффер деактивируется.
        Разрешено только участникам сделки.
        """
        if user.id not in (self.cargo.customer_id, self.carrier_id):
            raise PermissionDenied("Нельзя отклонить оффер: вы не участник сделки.")

        if self.is_active:
            self.is_active = False
            self.save(update_fields=["is_active", "updated_at"])