from django.contrib.auth.models import AbstractUser
from django.db import models

class UserRole(models.TextChoices):
    LOGISTIC = "LOGISTIC", "Логист"
    CUSTOMER = "CUSTOMER", "Заказчик"
    CARRIER  = "CARRIER",  "Перевозчик"

class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        default=None
    )
    company_name = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to="avatars/", blank=True, null=True)
    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.LOGISTIC)
    rating_as_customer = models.FloatField(default=0)
    rating_as_carrier  = models.FloatField(default=0)

    REQUIRED_FIELDS = ["email"]

    def save(self, *args, **kwargs):
        if self.phone == "":
            self.phone = None
        super().save(*args, **kwargs)

class EmailOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    code = models.CharField(max_length=6)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)