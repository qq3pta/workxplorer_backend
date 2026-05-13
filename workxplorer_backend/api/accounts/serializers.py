import logging
from datetime import timedelta

import phonenumbers
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, password_validation
from django.db.models import Avg, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from phonenumbers import PhoneNumberFormat
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .emails import send_code_email
from .models import EmailOTP, PhoneOTP, Profile, UserRole
from .utils.sms import check_sms_otp, send_sms_otp

User = get_user_model()

RESEND_COOLDOWN_SEC = 60


def normalize_phone_e164(phone: str, region: str = "UZ") -> str:
    try:
        p = phonenumbers.parse(phone, region)
        if not phonenumbers.is_valid_number(p):
            raise serializers.ValidationError({"phone": "Неверный номер телефона"})
        return phonenumbers.format_number(p, PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException as err:
        raise serializers.ValidationError({"phone": "Неверный номер телефона"}) from err


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


class UserDocumentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    order_id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True)
    category_display = serializers.CharField(read_only=True)
    file = serializers.FileField(read_only=True)
    file_name = serializers.CharField(read_only=True, allow_null=True)
    file_size = serializers.IntegerField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


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

        send_sms_otp(phone)

        PhoneOTP.objects.create(
            phone=phone,
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        return {
            "detail": "Код отправлен по SMS",
            "seconds_left": RESEND_COOLDOWN_SEC,
        }


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

        # Проверяем SMS код через Twilio
        check_sms_otp(phone, code)

        # Проверяем OTP запись в БД
        otp = (
            PhoneOTP.objects.filter(phone=phone, purpose=purpose, is_used=False)
            .order_by("-created_at")
            .first()
        )

        if not otp:
            raise serializers.ValidationError({"detail": "OTP не найден. Запросите код заново."})

        otp.is_used = True
        otp.save(update_fields=["is_used"])

        # Если пользователь существует — отмечаем verified
        user = User.objects.filter(phone=phone).first()
        if user:
            user.is_phone_verified = True
            user.save(update_fields=["is_phone_verified"])

        return {"verified": True}


class RegisterSerializer(serializers.ModelSerializer):
    phone = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)
    # inn = serializers.CharField(required=True, allow_blank=False, max_length=32)
    legal_address = serializers.CharField(required=False, allow_blank=True, max_length=500)
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
            # "inn",
            "legal_address",
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

        # inn = attrs.get("inn")
        # if not inn or not str(inn).strip():
        #     raise serializers.ValidationError({"inn": "Укажите ИНН"})
        # attrs["inn"] = str(inn).strip()

        if "legal_address" in attrs:
            attrs["legal_address"] = str(attrs.get("legal_address") or "").strip()

        email = attrs.get("email")
        if email and User.objects.filter(email__iexact=email).exists():
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
            purpose="verify",
            is_used=True,
            created_at__gte=since,
        ).exists()
        if not ok_recent:
            raise serializers.ValidationError({"phone": "Подтвердите номер по SMS-коду"})

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
            is_email_verified=False,
            is_phone_verified=True,
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
        from api.chat.services import sync_user_default_role_chat

        sync_user_default_role_chat(user)
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


logger = logging.getLogger(__name__)


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

            try:
                send_code_email(user.email, raw, purpose="verify")
                logger.info(f"OTP email sent successfully to {user.email}")
            except Exception as e:
                logger.error(f"Failed to send OTP email to {user.email}: {e}")
                raise serializers.ValidationError(
                    {"detail": "Не удалось отправить код по email. Попробуйте позже."}
                ) from e

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
    documents = serializers.SerializerMethodField()
    rating_as_customer = serializers.SerializerMethodField()
    rating_as_carrier = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "phone",
            "company_name",
            "inn",
            "legal_address",
            "photo",
            "role",
            "is_verified",
            "rating_as_customer",
            "rating_as_carrier",
            "is_phone_verified",
            "is_email_verified",
            "date_joined",
            "profile",
            "documents",
            "fcm_token",
            "is_accept_policy",
            "policy_accepted_at",
        )

        read_only_fields = (
            "id",
            "username",
            "email",
            "role",
            "is_verified",
            "rating_as_customer",
            "rating_as_carrier",
            "is_email_verified",
            "profile",
            "documents",
        )

    @extend_schema_field(UserDocumentSerializer(many=True))
    def get_documents(self, obj):
        from api.orders.models import OrderDocument

        documents = OrderDocument.objects.filter(uploaded_by=obj).order_by("-created_at")
        return [
            {
                "id": document.id,
                "order_id": document.order_id,
                "title": document.title,
                "category": document.category,
                "category_display": document.get_category_display(),
                "file": document.file.url if document.file else None,
                "file_name": document.file.name.rsplit("/", 1)[-1] if document.file else None,
                "file_size": self._get_document_file_size(document),
                "created_at": document.created_at,
            }
            for document in documents
        ]

    def _get_document_file_size(self, document):
        if not document.file:
            return None
        try:
            return int(document.file.size)
        except (FileNotFoundError, OSError):
            return None

    def _get_dynamic_rating(self, obj) -> float:
        avg = obj.ratings_received.aggregate(value=Avg("score"))["value"]
        return round(float(avg or 0), 1)

    @extend_schema_field(serializers.FloatField())
    def get_rating_as_customer(self, obj):
        return self._get_dynamic_rating(obj)

    @extend_schema_field(serializers.FloatField())
    def get_rating_as_carrier(self, obj):
        return self._get_dynamic_rating(obj)


class UpdateMeSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)
    fcm_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_accept_policy = serializers.BooleanField(required=False)

    class Meta:
        model = User
        fields = (
            "first_name",
            "phone",
            "company_name",
            "inn",
            "legal_address",
            "photo",
            "profile",
            "fcm_token",
            "is_accept_policy",
        )

    def validate_phone(self, value):
        norm = normalize_phone_e164(value) if value else value
        if norm and User.objects.filter(phone=norm).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Этот телефон уже зарегистрирован")
        return norm

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)

        if "is_accept_policy" in validated_data:
            if validated_data["is_accept_policy"] is True and not instance.is_accept_policy:
                instance.is_accept_policy = True
                instance.policy_accepted_at = timezone.now()
            validated_data.pop("is_accept_policy", None)

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


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user

        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": "Неверный текущий пароль"})

        password_validation.validate_password(
            attrs["new_password"],
            user=user,
        )

        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return {"detail": "Пароль успешно изменён"}


class RoleChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=UserRole.choices)

    def save(self, **kwargs):
        user = self.context["request"].user
        new_role = self.validated_data["role"]
        if user.role == new_role:
            return {"detail": "Роль уже установлена"}
        user.role = new_role
        user.save(update_fields=["role"])
        from api.chat.services import sync_user_default_role_chat

        sync_user_default_role_chat(user, emit_events=True)
        return {"detail": "Роль обновлена", "role": user.role}


class SendEmailVerifyFromProfileSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        user = self.context["request"].user
        email = self.validated_data["email"]

        if User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
            raise serializers.ValidationError({"email": "Этот e-mail уже используется"})

        if user.email != email:
            user.email = email
            user.is_email_verified = False
            user.save(update_fields=["email", "is_email_verified"])

        last = (
            EmailOTP.objects.filter(
                user=user,
                purpose=EmailOTP.PURPOSE_VERIFY,
            )
            .order_by("-created_at")
            .first()
        )

        if last:
            diff = (timezone.now() - last.created_at).total_seconds()
            left = max(0, RESEND_COOLDOWN_SEC - int(diff))
            if left > 0:
                raise serializers.ValidationError(
                    {"detail": "Код уже отправлен", "seconds_left": left}
                )

        otp, raw = EmailOTP.create_otp(
            user=user,
            purpose=EmailOTP.PURPOSE_VERIFY,
            ttl_min=15,
        )

        send_code_email(email, raw, purpose="verify")

        return {
            "detail": "Код отправлен на e-mail",
            "seconds_left": RESEND_COOLDOWN_SEC,
        }


class AvatarUploadSerializer(serializers.Serializer):
    photo = serializers.ImageField(write_only=True)

    ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")

    def validate_photo(self, value):
        max_bytes = int(getattr(settings, "MAX_UPLOAD_MB", 20)) * 1024 * 1024
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f"Файл слишком большой (максимум {max_bytes // (1024 * 1024)} МБ)"
            )
        ctype = getattr(value, "content_type", None)
        if ctype and ctype not in self.ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError("Допустимые форматы: JPEG, PNG, WEBP, GIF")
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        photo = self.validated_data["photo"]

        if user.photo:
            try:
                user.photo.delete(save=False)
            except Exception:
                pass

        user.photo = photo
        user.save(update_fields=["photo"])
        return user


class VerifyEmailFromProfileSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=6)

    def save(self, **kwargs):
        user = self.context["request"].user
        code = self.validated_data["code"]

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
            user.save(update_fields=["is_email_verified"])

        return {"detail": "E-mail подтвержден"}
