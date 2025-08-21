from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, EmailOTP, UserRole

@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "code", "is_used", "created_at")
    list_filter = ("is_used", "created_at")
    search_fields = ("user__username", "user__email", "code")
    readonly_fields = ("user", "code", "is_used", "created_at")

class EmailOTPInline(admin.TabularInline):
    model = EmailOTP
    fields = ("code", "is_used", "created_at")
    readonly_fields = ("code", "is_used", "created_at")
    extra = 0
    can_delete = False

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "id", "username", "email", "role",
        "company_name", "phone",
        "rating_as_customer", "rating_as_carrier",
        "is_active", "is_staff", "date_joined",
    )
    list_filter = ("role", "is_active", "is_staff", "is_superuser", "date_joined")
    search_fields = ("username", "email", "company_name", "phone")
    ordering = ("-date_joined",)
    readonly_fields = ("last_login", "date_joined")

    fieldsets = (
        ("Аккаунт", {"fields": ("username", "password")}),
        ("Профиль", {"fields": ("photo", "company_name", "phone", "role",
                                 "rating_as_customer", "rating_as_carrier")}),
        ("Контакты", {"fields": ("email",)}),
        ("Права", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Системное", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2", "role", "is_active", "is_staff"),
        }),
    )

    inlines = [EmailOTPInline]