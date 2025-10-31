from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _


class UserRating(models.Model):
    """
    Оценки участников перевозки (клиент ⇄ логист / перевозчик).
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
        verbose_name=_("Заказ, в рамках которого выставлена оценка"),
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
        ]

    def __str__(self):
        return f"{self.rated_by} → {self.rated_user} ({self.score}⭐)"
