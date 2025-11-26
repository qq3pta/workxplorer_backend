from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from api.notifications.services import notify


class UserRating(models.Model):
    """
    Оценки участников перевозки.
    Один пользователь может оценить другого только 1 раз в рамках одного заказа.
    """

    rated_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ratings_received",
        verbose_name=_("Оцениваемый пользователь"),
    )
    rated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ratings_given",
        verbose_name=_("Кто поставил оценку"),
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="ratings",
        verbose_name=_("Заказ"),
    )

    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_("Оценка (1–5)"),
    )
    comment = models.TextField(blank=True, null=True, verbose_name=_("Комментарий"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Оценка пользователя")
        verbose_name_plural = _("Оценки пользователей")
        unique_together = ("rated_user", "order")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["rated_user"]),
            models.Index(fields=["rated_by"]),
            models.Index(fields=["order"]),
            models.Index(fields=["score"]),
        ]

    def __str__(self):
        return f"{self.rated_by} → {self.rated_user} ({self.score}⭐)"

    def clean(self):
        if self.rated_user_id == self.rated_by_id:
            raise ValidationError("Пользователь не может оценить сам себя.")

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        super().save(*args, **kwargs)

        if not is_new:
            return

        def after_commit():
            # Получатель рейтинга
            notify(
                user=self.rated_user,
                type="rating_received",
                title="Получена новая оценка",
                message=f"Вам поставили оценку: {self.score} ⭐",
                payload={
                    "order_id": self.order_id,
                    "rated_by": self.rated_by_id,
                    "score": self.score,
                },
                cargo=self.order.cargo,
            )

            notify(
                user=self.rated_by,
                type="rating_sent",
                title="Оценка отправлена",
                message=f"Вы поставили оценку пользователю {self.rated_user}",
                payload={
                    "order_id": self.order_id,
                    "rated_user": self.rated_user_id,
                    "score": self.score,
                },
                cargo=self.order.cargo,
            )

        transaction.on_commit(after_commit)
