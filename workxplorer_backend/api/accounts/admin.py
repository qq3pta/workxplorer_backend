from django.contrib import admin

from .models import EmailOTP, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "username",
        "email",
        "role",
        "is_email_verified",
        "rating_as_customer",
        "rating_as_carrier",
    )
    list_filter = ("role", "is_email_verified")
    search_fields = ("username", "email", "phone", "company_name")


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "purpose",
        "code",
        "is_used",
        "expires_at",
        "attempts_left",
        "created_at",
    )
    list_filter = ("purpose", "is_used")
    search_fields = ("user__username", "user__email", "code")
