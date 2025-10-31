import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import UniqueConstraint, Avg, Q
from django.db.models.functions import Lower
from django.utils import timezone


class UserRole(models.TextChoices):
    LOGISTIC = "LOGISTIC", "Логист"
    CUSTOMER = "CUSTOMER", "Заказчик"
    CARRIER = "CARRIER", "Перевозчик"


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, unique=True, blank=True, null=True, default=None)
    company_name = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to="avatars/", blank=True, null=True)

    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.LOGISTIC)

    rating_as_customer = models.FloatField(default=0)
    rating_as_carrier = models.FloatField(default=0)
    is_email_verified = models.BooleanField(default=False)

    REQUIRED_FIELDS = ["email"]

    class Meta:
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["phone"]),
        ]
        constraints = [
            UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
            UniqueConstraint(Lower("username"), name="user_username_ci_unique"),
        ]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        if self.phone == "":
            self.phone = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username or self.email or f"User#{self.pk}"

    # --- Вспомогательные проверки роли ---
    @property
    def is_logistic(self) -> bool:
        return self.role == UserRole.LOGISTIC

    @property
    def is_customer(self) -> bool:
        return self.role == UserRole.CUSTOMER

    @property
    def is_carrier(self) -> bool:
        return self.role == UserRole.CARRIER

    # --- Новые вычисляемые поля рейтингов и заказов ---
    @property
    def avg_rating(self):
        """Средний рейтинг пользователя (по всем оценкам, где он был оцениваемым)."""
        from api.ratings.models import UserRating

        avg = UserRating.objects.filter(rated_user=self).aggregate(avg=Avg("score"))["avg"]
        return round(avg or 0, 1)

    @property
    def rating_count(self):
        """Количество полученных отзывов/оценок."""
        from api.ratings.models import UserRating

        return UserRating.objects.filter(rated_user=self).count()

    @property
    def completed_orders(self):
        """Количество завершённых заказов для перевозчика."""
        from api.orders.models import Order

        return Order.objects.filter(carrier=self, status="delivered").count()


class EmailOTP(models.Model):
    PURPOSE_VERIFY = "verify"
    PURPOSE_RESET = "reset"
    PURPOSES = [(PURPOSE_VERIFY, "verify"), (PURPOSE_RESET, "reset")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=10, choices=PURPOSES, default=PURPOSE_VERIFY)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts_left = models.PositiveSmallIntegerField(default=5)

    class Meta:
        indexes = [
            models.Index(fields=["user", "purpose", "-created_at"]),
            models.Index(fields=["purpose", "is_used"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id}:{self.purpose}:{self.code}"

    @staticmethod
    def create_otp(user, purpose: str, ttl_min: int = 15):
        raw = f"{secrets.randbelow(10**6):06d}"
        obj = EmailOTP.objects.create(
            user=user,
            code=raw,
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=ttl_min),
        )
        return obj, raw

    def check_and_consume(self, raw_code: str) -> bool:
        if self.is_used or self.expires_at < timezone.now() or self.attempts_left == 0:
            return False
        ok = self.code == raw_code
        if ok:
            self.is_used = True
            self.save(update_fields=["is_used"])
            return True
        self.attempts_left = max(0, self.attempts_left - 1)
        self.save(update_fields=["attempts_left"])
        return False


class PhoneOTP(models.Model):
    """OTP по телефону (для WhatsApp/SMS)."""

    PURPOSE_VERIFY = "verify"
    PURPOSE_RESET = "reset"
    PURPOSES = [(PURPOSE_VERIFY, "verify"), (PURPOSE_RESET, "reset")]

    phone = models.CharField(max_length=20, db_index=True)
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=10, choices=PURPOSES, default=PURPOSE_VERIFY)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts_left = models.PositiveSmallIntegerField(default=5)

    class Meta:
        indexes = [
            models.Index(fields=["phone", "purpose", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.phone}:{self.purpose}:{self.code}"

    @staticmethod
    def create_otp(phone: str, purpose: str, ttl_min: int = 5):
        raw = f"{secrets.randbelow(10**6):06d}"
        obj = PhoneOTP.objects.create(
            phone=phone,
            code=raw,
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=ttl_min),
        )
        return obj, raw

    def check_and_consume(self, raw_code: str) -> bool:
        if self.is_used or self.expires_at < timezone.now() or self.attempts_left == 0:
            return False
        ok = self.code == raw_code
        if ok:
            self.is_used = True
            self.save(update_fields=["is_used"])
            return True
        self.attempts_left = max(0, self.attempts_left - 1)
        self.save(update_fields=["attempts_left"])
        return False


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    country = models.CharField("Страна", max_length=64, blank=True)
    country_code = models.CharField("Код страны (ISO-2)", max_length=2, blank=True)
    region = models.CharField("Регион/область", max_length=128, blank=True)
    city = models.CharField("Город", max_length=128, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"

    def __str__(self):
        return f"Profile<{self.user_id}> {self.country}/{self.city}"
