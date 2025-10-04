from django.contrib import admin

from .models import EmailOTP, User, Profile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    extra = 0
    fk_name = "user"
    fields = ("country", "country_code", "region", "city")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    inlines = [ProfileInline]

    list_display = (
        "id",
        "username",
        "email",
        "role",
        "is_email_verified",
        "rating_as_customer",
        "rating_as_carrier",
        "profile_country",
        "profile_city",
    )
    list_filter = ("role", "is_email_verified")
    search_fields = ("username", "email", "phone", "company_name", "profile__city", "profile__country")

    def profile_country(self, obj):
        return getattr(obj.profile, "country", "")
    profile_country.short_description = "Country"

    def profile_city(self, obj):
        return getattr(obj.profile, "city", "")
    profile_city.short_description = "City"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "country", "country_code", "region", "city")
    list_filter = ("country_code",)
    search_fields = ("user__username", "user__email", "city", "country", "country_code")


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