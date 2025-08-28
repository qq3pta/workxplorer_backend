from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower
from django.utils import timezone
from datetime import timedelta
import secrets


class UserRole(models.TextChoices):
    LOGISTIC = "LOGISTIC", "Логист"
    CUSTOMER = "CUSTOMER", "Заказчик"
    CARRIER  = "CARRIER",  "Перевозчик"


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, unique=True, blank=True, null=True, default=None)
    company_name = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to="avatars/", blank=True, null=True)

    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.LOGISTIC)

    rating_as_customer = models.FloatField(default=0)
    rating_as_carrier  = models.FloatField(default=0)

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

    @property
    def is_logistic(self) -> bool:
        return self.role == UserRole.LOGISTIC

    @property
    def is_customer(self) -> bool:
        return self.role == UserRole.CUSTOMER

    @property
    def is_carrier(self) -> bool:
        return self.role == UserRole.CARRIER


class EmailOTP(models.Model):
    PURPOSE_VERIFY = "verify"
    PURPOSE_RESET  = "reset"
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
        ok = (self.code == raw_code)
        if ok:
            self.is_used = True
            self.save(update_fields=["is_used"])
            return True
        self.attempts_left = max(0, self.attempts_left - 1)
        self.save(update_fields=["attempts_left"])
        return False