from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError, PermissionDenied
from decimal import Decimal
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

    # --- CUSTOMER ---
    customer_id = models.BigIntegerField(null=True, blank=True)
    customer_full_name = models.CharField(max_length=255, blank=True, default="")
    customer_email = models.EmailField(blank=True, default="")
    customer_phone = models.CharField(max_length=32, blank=True, default="")
    customer_registered_at = models.DateTimeField(null=True, blank=True)

    # --- CARRIER ---
    carrier_id = models.BigIntegerField(null=True, blank=True)
    carrier_full_name = models.CharField(max_length=255, blank=True)
    carrier_email = models.EmailField(blank=True)
    carrier_phone = models.CharField(max_length=32, blank=True)
    carrier_registered_at = models.DateTimeField(null=True, blank=True)

    # --- LOGISTIC ---
    logistic_id = models.BigIntegerField(null=True, blank=True)
    logistic_full_name = models.CharField(max_length=255, blank=True)
    logistic_email = models.EmailField(blank=True)
    logistic_phone = models.CharField(max_length=32, blank=True)
    logistic_registered_at = models.DateTimeField(null=True, blank=True)

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
        customer = offer.cargo.customer
        carrier = offer.carrier
        logistic = offer.intermediary or offer.logistic

        defaults = {
            "expires_at": timezone.now() + timedelta(minutes=30),
            # --- CUSTOMER SNAPSHOT ---
            "customer_id": customer.id,
            "customer_full_name": customer.get_full_name(),
            "customer_email": customer.email,
            "customer_phone": customer.phone,
            "customer_registered_at": customer.date_joined,
        }

        # --- CARRIER SNAPSHOT ---
        if carrier:
            defaults.update(
                {
                    "carrier_id": carrier.id,
                    "carrier_full_name": carrier.get_full_name(),
                    "carrier_email": carrier.email,
                    "carrier_phone": carrier.phone,
                    "carrier_registered_at": carrier.date_joined,
                }
            )

        # --- LOGISTIC SNAPSHOT ---
        if logistic:
            defaults.update(
                {
                    "logistic_id": logistic.id,
                    "logistic_full_name": logistic.get_full_name(),
                    "logistic_email": logistic.email,
                    "logistic_phone": logistic.phone,
                    "logistic_registered_at": logistic.date_joined,
                }
            )

        agreement, _ = cls.objects.get_or_create(
            offer=offer,
            defaults=defaults,
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

        # ✅ ЗАКАЗЧИК ПО ID (включая LOGISTIC-заказчика)
        if user.id in (cargo.customer_id, cargo.created_by_id):
            self.accepted_by_customer = True
            accepted_as_participant = True

        # ✅ ПЕРЕВОЗЧИК
        elif user.id == offer.carrier_id:
            self.accepted_by_carrier = True
            accepted_as_participant = True

        # ✅ ЛОГИСТ / ПОСРЕДНИК
        elif user.id in (offer.logistic_id, offer.intermediary_id):
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

            # -------- РАССТОЯНИЕ --------
            if cargo.route_km_cached:
                route_km = Decimal(cargo.route_km_cached)

            elif cargo.origin_point and cargo.dest_point:
                meters = cargo.origin_point.distance(cargo.dest_point)
                route_km = Decimal(meters / 1000)

            else:
                route_km = Decimal("0")

            if route_km <= 0:
                raise ValidationError("Не удалось рассчитать расстояние маршрута")

            # -------- ЦЕНА --------
            price_total = offer.price_value or Decimal("0.00")

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
                payment_method=offer.payment_method,
                price_total=price_total,
                route_distance_km=route_km.quantize(Decimal("0.01")),
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

    def reject(self, by_user):
        if self.status != self.Status.PENDING:
            raise ValidationError("Соглашение уже обработано")

        offer = self.offer
        cargo = offer.cargo

        # 🔐 Проверка участия (симметрично accept_by)
        if by_user.id in (cargo.customer_id, cargo.created_by_id):
            pass  # заказчик
        elif by_user.id == offer.carrier_id:
            pass  # перевозчик
        elif by_user.id in (offer.logistic_id, offer.intermediary_id):
            pass  # логист / посредник
        else:
            raise PermissionDenied("Вы не участник соглашения")

        # ❌ Отмена соглашения
        self.status = self.Status.CANCELLED
        self.save(update_fields=["status"])

        # ❌ Деактивируем оффер
        offer.is_active = False
        offer.save(update_fields=["is_active"])
