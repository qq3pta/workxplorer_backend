import phonenumbers

from phonenumbers import PhoneNumberFormat
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, password_validation
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .emails import send_code_email
from .models import EmailOTP, PhoneOTP, Profile, UserRole
from .utils.whatsapp import send_whatsapp_otp, check_whatsapp_otp

User = get_user_model()

RESEND_COOLDOWN_SEC = 60


def normalize_phone_e164(phone: str, region: str = "UZ") -> str:
    try:
        p = phonenumbers.parse(phone, region)
        if not phonenumbers.is_valid_number(p):
            raise serializers.ValidationError({"phone": "Неверный номер телефона"})
        return phonenumbers.format_number(p, PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        raise serializers.ValidationError({"phone": "Неверный номер телефона"})


def _normalize_phone(p: str) -> str:
    """Оставляем только цифры и ведущий '+', чтобы унифицировать хранение/поиск."""
    if not p:
        return p
    raw = "".join(ch for ch in str(p) if ch.isdigit() or ch == "+")
    if raw.count("+") > 1:
        raw = raw.replace("+", "")
    if raw and raw[0] != "+" and raw.count("+") > 0:
        raw = raw.replace("+", "")
    return raw


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ("country", "country_code", "region", "city")

    def validate(self, attrs):
        if attrs.get("country") and not attrs.get("country_code"):
            raise serializers.ValidationError(
                {"country_code": "Укажи ISO-2 код страны (например, UZ)."}
            )
        return attrs


class SendPhoneOTPSerializer(serializers.Serializer):
    phone = serializers.CharField()
    purpose = serializers.ChoiceField(
        choices=[("verify", "verify"), ("reset", "reset")], default="verify"
    )

    def validate(self, attrs):
        phone = attrs.get("phone")
        if not phone or not str(phone).strip():
            raise serializers.ValidationError({"phone": "Укажите номер телефона"})

        attrs["phone"] = normalize_phone_e164(phone)

        return attrs

    def save(self, **kwargs):
        phone = self.validated_data["phone"]
        purpose = self.validated_data["purpose"]

        last = PhoneOTP.objects.filter(phone=phone, purpose=purpose).order_by("-created_at").first()
        if last:
            diff = (timezone.now() - last.created_at).total_seconds()
            left = max(0, RESEND_COOLDOWN_SEC - int(diff))
            if left > 0:
                raise serializers.ValidationError(
                    {"detail": "Код уже отправлен. Подождите.", "seconds_left": left}
                )

        ok = send_whatsapp_otp(phone)
        if not ok:
            raise serializers.ValidationError({"phone": "Не удалось отправить код в WhatsApp"})

        PhoneOTP.objects.create(
            phone=phone,
            purpose=purpose,
        )

        return {"detail": "Код отправлен в WhatsApp", "seconds_left": RESEND_COOLDOWN_SEC}


class VerifyPhoneOTPSerializer(serializers.Serializer):
    phone = serializers.CharField()
    code = serializers.CharField(max_length=6)
    purpose = serializers.ChoiceField(
        choices=[("verify", "verify"), ("reset", "reset")], default="verify"
    )

    def validate(self, attrs):
        phone = attrs.get("phone")
        if not phone or not str(phone).strip():
            raise serializers.ValidationError({"phone": "Укажите номер телефона"})

        attrs["phone"] = normalize_phone_e164(phone)

        return attrs

    def save(self, **kwargs):
        phone = self.validated_data["phone"]
        code = self.validated_data["code"]
        purpose = self.validated_data["purpose"]

        ok = check_whatsapp_otp(phone, code)
        if not ok:
            raise serializers.ValidationError({"code": "Неверный или просроченный код"})

        since = timezone.now() - timedelta(minutes=10)

        updated = PhoneOTP.objects.filter(
            phone=phone,
            purpose=purpose,
            is_used=False,
            created_at__gte=since,
        ).update(is_used=True)

        if updated == 0:
            raise serializers.ValidationError({"detail": "Код устарел, запросите новый"})


class RegisterSerializer(serializers.ModelSerializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)
    fcm_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    country = serializers.CharField(required=False, allow_blank=True)
    country_code = serializers.CharField(required=False, allow_blank=True, max_length=2)
    region = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password",
            "password2",
            "first_name",
            "phone",
            "company_name",
            "role",
            "country",
            "country_code",
            "region",
            "city",
            "fcm_token",
        )

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password2"):
            raise serializers.ValidationError({"password": "Пароли не совпадают"})

        phone = attrs.get("phone")
        if not phone or not str(phone).strip():
            raise serializers.ValidationError({"phone": "Укажите номер телефона"})

        attrs["phone"] = normalize_phone_e164(phone)

        if User.objects.filter(email__iexact=attrs["email"]).exists():
            raise serializers.ValidationError({"email": "Этот e-mail уже зарегистрирован"})
        if User.objects.filter(username__iexact=attrs["username"]).exists():
            raise serializers.ValidationError({"username": "Этот логин уже занят"})
        if User.objects.filter(phone=attrs["phone"]).exists():
            raise serializers.ValidationError({"phone": "Этот телефон уже зарегистрирован"})
        if attrs.get("country") and not attrs.get("country_code"):
            raise serializers.ValidationError(
                {"country_code": "Укажи ISO-2 код страны (например, UZ)."}
            )

        recent_minutes = int(getattr(settings, "OTP_RECENT_MINUTES", 10))
        since = timezone.now() - timedelta(minutes=recent_minutes)
        ok_recent = PhoneOTP.objects.filter(
            phone=attrs["phone"],
            purpose=PhoneOTP.PURPOSE_VERIFY,
            is_used=True,
            created_at__gte=since,
        ).exists()
        if not ok_recent:
            raise serializers.ValidationError({"phone": "Подтвердите номер через WhatsApp-OTP"})

        password_validation.validate_password(attrs["password"])
        return attrs

    def create(self, validated):
        profile_fields = ("country", "country_code", "region", "city")
        profile_data = {k: validated.pop(k, None) for k in list(profile_fields)}

        token = validated.pop("fcm_token", None)

        pwd = validated.pop("password")
        role = validated.pop("role", UserRole.CUSTOMER)
        user = User.objects.create(
            role=role,
            is_active=True,
            is_email_verified=True,
            **validated,
        )
        user.set_password(pwd)
        user.save()

        if token:
            user.fcm_token = token
            user.save(update_fields=["fcm_token"])

        Profile.objects.update_or_create(
            user=user, defaults={k: v for k, v in profile_data.items() if v is not None}
        )
        return user


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def save(self, **kwargs):
        email = self.validated_data["email"]
        code = self.validated_data["code"]
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise serializers.ValidationError({"email": "Пользователь не найден"})
        otp = (
            EmailOTP.objects.filter(
                user=user,
                purpose=EmailOTP.PURPOSE_VERIFY,
                is_used=False,
                expires_at__gte=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if not otp or not otp.check_and_consume(code):
            raise serializers.ValidationError({"code": "Неверный или просроченный код"})

        if not user.is_email_verified:
            user.is_email_verified = True
            user.is_active = True
            user.save(update_fields=["is_email_verified", "is_active"])
        return user


class ResendVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        email = self.validated_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        if user and not user.is_email_verified:
            last = (
                EmailOTP.objects.filter(user=user, purpose=EmailOTP.PURPOSE_VERIFY)
                .order_by("-created_at")
                .first()
            )
            if last:
                diff = (timezone.now() - last.created_at).total_seconds()
                left = max(0, RESEND_COOLDOWN_SEC - int(diff))
                if left > 0:
                    raise serializers.ValidationError(
                        {"detail": "Код уже отправлен. Подождите.", "seconds_left": left}
                    )

            otp, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_VERIFY, ttl_min=15)
            send_code_email(user.email, raw, purpose="verify")

        return {
            "detail": "Если e-mail существует — код отправлен",
            "seconds_left": RESEND_COOLDOWN_SEC,
        }


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField()
    remember_me = serializers.BooleanField(default=False)
    fcm_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        login = attrs["login"]
        password = attrs["password"]
        u = User.objects.filter(Q(email__iexact=login) | Q(username__iexact=login)).first()
        if not u:
            raise serializers.ValidationError({"detail": "Неверные учетные данные"})
        user = authenticate(username=u.username, password=password)
        if not user:
            raise serializers.ValidationError({"detail": "Неверные учетные данные"})
        if not user.is_email_verified:
            raise serializers.ValidationError({"detail": "Аккаунт не подтверждён"})

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        if attrs.get("remember_me"):
            refresh.set_exp(lifetime=timedelta(days=30))
            access.set_exp(lifetime=timedelta(hours=12))

        attrs["tokens"] = {"access": str(access), "refresh": str(refresh)}
        attrs["user"] = user
        return attrs


class MeSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "phone",
            "company_name",
            "photo",
            "role",
            "rating_as_customer",
            "rating_as_carrier",
            "is_email_verified",
            "date_joined",
            "profile",
            "fcm_token",
        )

        read_only_fields = (
            "id",
            "username",
            "email",
            "role",
            "rating_as_customer",
            "rating_as_carrier",
            "is_email_verified",
            "profile",
        )


class UpdateMeSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)
    fcm_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = ("first_name", "phone", "company_name", "photo", "profile", "fcm_token")

    def validate_phone(self, value):
        norm = _normalize_phone(value) if value else value
        if norm and User.objects.filter(phone=norm).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Этот телефон уже зарегистрирован")
        return norm

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)

        if "fcm_token" in validated_data:
            instance.fcm_token = validated_data["fcm_token"]

        user = super().update(instance, validated_data)

        if profile_data is not None:
            prof, _ = Profile.objects.get_or_create(user=user)
            for k, v in profile_data.items():
                setattr(prof, k, v)
            prof.save()

        return user


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        email = self.validated_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        if user:
            last = (
                EmailOTP.objects.filter(user=user, purpose=EmailOTP.PURPOSE_RESET)
                .order_by("-created_at")
                .first()
            )
            if last:
                diff = (timezone.now() - last.created_at).total_seconds()
                left = max(0, RESEND_COOLDOWN_SEC - int(diff))
                if left > 0:
                    raise serializers.ValidationError(
                        {"detail": "Код уже отправлен. Подождите.", "seconds_left": left}
                    )
            otp, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_RESET, ttl_min=15)
            send_code_email(user.email, raw, purpose="reset")
        return {
            "detail": "Если e-mail существует — код отправлен",
            "seconds_left": RESEND_COOLDOWN_SEC,
        }


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)
    new_password = serializers.CharField()

    def validate(self, attrs):
        user = User.objects.filter(email__iexact=attrs["email"]).first()
        password_validation.validate_password(attrs["new_password"], user=user)
        return attrs

    def save(self, **kwargs):
        email = self.validated_data["email"]
        code = self.validated_data["code"]
        newp = self.validated_data["new_password"]

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise serializers.ValidationError({"email": "Пользователь не найден"})

        otp = (
            EmailOTP.objects.filter(
                user=user,
                purpose=EmailOTP.PURPOSE_RESET,
                is_used=False,
                expires_at__gte=timezone.now(),
                code=code,
            )
            .order_by("-created_at")
            .first()
        )
        if not otp or not otp.check_and_consume(code):
            raise serializers.ValidationError({"code": "Неверный или просроченный код"})

        user.set_password(newp)
        user.save(update_fields=["password"])
        return {"detail": "Пароль обновлен"}


class RoleChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=UserRole.choices)

    def save(self, **kwargs):
        user = self.context["request"].user
        new_role = self.validated_data["role"]
        if user.role == new_role:
            return {"detail": "Роль уже установлена"}
        user.role = new_role
        user.save(update_fields=["role"])
        return {"detail": "Роль обновлена", "role": user.role}


class AnalyticsSerializer(serializers.Serializer):
    successful_deliveries = serializers.IntegerField()
    successful_deliveries_change = serializers.FloatField()
    registered_since = serializers.DateField()
    days_since_registered = serializers.IntegerField()
    rating = serializers.FloatField()
    distance_km = serializers.FloatField()
    deals_count = serializers.IntegerField()
