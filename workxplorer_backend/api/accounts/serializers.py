from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model, password_validation
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .emails import send_code_email
from .models import EmailOTP, UserRole

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

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
        )

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password2"):
            raise serializers.ValidationError({"password": "Пароли не совпадают"})

        phone = attrs.get("phone")
        if not phone or not str(phone).strip():
            raise serializers.ValidationError({"phone": "Укажите номер телефона"})

        if User.objects.filter(email__iexact=attrs["email"]).exists():
            raise serializers.ValidationError({"email": "Этот e-mail уже зарегистрирован"})
        if User.objects.filter(username__iexact=attrs["username"]).exists():
            raise serializers.ValidationError({"username": "Этот логин уже занят"})
        if User.objects.filter(phone=attrs["phone"]).exists():
            raise serializers.ValidationError({"phone": "Этот телефон уже зарегистрирован"})

        password_validation.validate_password(attrs["password"])
        return attrs

    def create(self, validated):
        pwd = validated.pop("password")
        user = User.objects.create(
            role=UserRole.LOGISTIC,  # по ТЗ дефолт — логист
            is_active=False,  # до подтверждения email
            is_email_verified=False,
            **validated,
        )
        user.set_password(pwd)
        user.save()

        otp, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_VERIFY, ttl_min=15)
        send_code_email(user.email, raw, purpose="verify")
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
            # anti-abuse: не чаще 1 раза в минуту
            last = (
                EmailOTP.objects.filter(user=user, purpose=EmailOTP.PURPOSE_VERIFY)
                .order_by("-created_at")
                .first()
            )
            if last and (timezone.now() - last.created_at).total_seconds() < 60:
                raise serializers.ValidationError(
                    {"detail": "Код уже отправлен. Подождите минуту."}
                )

            otp, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_VERIFY, ttl_min=15)
            send_code_email(user.email, raw, purpose="verify")
        return {"detail": "Если e-mail существует — код отправлен"}


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField()
    remember_me = serializers.BooleanField(default=False)

    def validate(self, attrs):
        login = attrs["login"]
        password = attrs["password"]
        u = User.objects.filter(Q(email__iexact=login) | Q(username__iexact=login)).first()
        username = u.username if u else login
        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError({"detail": "Неверные учетные данные"})
        if not user.is_email_verified:
            raise serializers.ValidationError({"detail": "Email не подтвержден"})

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        if attrs.get("remember_me"):
            refresh.set_exp(lifetime=timedelta(days=30))
            access.set_exp(lifetime=timedelta(hours=12))  # можно скорректировать под продукт

        attrs["tokens"] = {"access": str(access), "refresh": str(refresh)}
        attrs["user"] = user
        return attrs


class MeSerializer(serializers.ModelSerializer):
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
        )
        read_only_fields = (
            "id",
            "username",
            "email",
            "role",
            "rating_as_customer",
            "rating_as_carrier",
            "is_email_verified",
        )


class UpdateMeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # Роль исключена — меняется отдельной ручкой (ChangeRoleView)
        fields = ("first_name", "phone", "company_name", "photo")

    def validate_phone(self, value):
        if value and User.objects.filter(phone=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Этот телефон уже зарегистрирован")
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        email = self.validated_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        if user:
            otp, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_RESET, ttl_min=15)
            send_code_email(user.email, raw, purpose="reset")
        return {"detail": "Если e-mail существует — код отправлен"}


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


# --- Отдельный сериализатор для смены роли (по ТЗ) ---
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
