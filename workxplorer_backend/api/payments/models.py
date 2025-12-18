from django.db import models
from django.utils import timezone


class PaymentStatus:
    PENDING = "PENDING"
    CONFIRMED_BY_CUSTOMER = "CONFIRMED_BY_CUSTOMER"
    CONFIRMED_BY_CARRIER = "CONFIRMED_BY_CARRIER"
    COMPLETED = "COMPLETED"

    choices = [
        (PENDING, "Создано"),
        (CONFIRMED_BY_CUSTOMER, "Оплачено заказчиком"),
        (CONFIRMED_BY_CARRIER, "Получено перевозчиком"),
        (COMPLETED, "Завершено"),
    ]


class PaymentMethod:
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"

    choices = [
        (CASH, "Наличные"),
        (BANK_TRANSFER, "Перечисление"),
    ]


class Payment(models.Model):
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="payments")

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="UZS")

    # Статусы подтверждения
    confirmed_by_customer = models.BooleanField(default=False)
    confirmed_by_logistic = models.BooleanField(default=False)
    confirmed_by_carrier = models.BooleanField(default=False)

    # Информация для внешних платежных систем (если будут)
    external_transaction_id = models.CharField(max_length=100, null=True, blank=True)

    # Теперь реальные методы оплаты:
    method = models.CharField(
        max_length=32,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )

    status = models.CharField(
        max_length=32, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def update_status(self):
        order = self.order
        needs_logistic = order.logistic is not None

        if (
            self.confirmed_by_customer
            and self.confirmed_by_carrier
            and (not needs_logistic or self.confirmed_by_logistic)
        ):
            self.status = PaymentStatus.COMPLETED
            self.completed_at = timezone.now()

        elif self.confirmed_by_customer:
            self.status = PaymentStatus.CONFIRMED_BY_CUSTOMER

        elif self.confirmed_by_carrier:
            self.status = PaymentStatus.CONFIRMED_BY_CARRIER

        else:
            self.status = PaymentStatus.PENDING

        self.save(update_fields=["status", "completed_at"])
