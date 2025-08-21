from django.contrib.auth import get_user_model, authenticate, password_validation
from rest_framework import serializers
from .models import EmailOTP, UserRole
from .emails import send_code_email

User = get_user_model()

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ("username","email","password","password2","first_name","phone","company_name")

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password2"):
            raise serializers.ValidationError({"password": "Пароли не совпадают"})
        password_validation.validate_password(attrs["password"])
        return attrs

    def create(self, validated):
        pwd = validated.pop("password")
        # стартовая роль — логист
        user = User.objects.create(role=UserRole.LOGISTIC, **validated)
        user.set_password(pwd)
        user.save()
        _, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_VERIFY, ttl_min=15)
        send_code_email(user.email, raw, purpose="verify")
        return user

class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def save(self, **kwargs):
        email = self.validated_data["email"]
        code  = self.validated_data["code"]
        user = User.objects.filter(email=email).first()
        if not user:
            raise serializers.ValidationError({"email": "Пользователь не найден"})
        otp = (EmailOTP.objects
               .filter(user=user, purpose=EmailOTP.PURPOSE_VERIFY, is_used=False)
               .order_by("-created_at").first())
        if not otp or not otp.check_and_consume(code):
            raise serializers.ValidationError({"code": "Неверный или просроченный код"})
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])
        return user

class ResendVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    def save(self, **kwargs):
        email = self.validated_data["email"]
        user = User.objects.filter(email=email).first()
        if user and not user.is_email_verified:
            _, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_VERIFY, ttl_min=15)
            send_code_email(user.email, raw, purpose="verify")
        return {"detail": "Если e-mail существует — код отправлен"}

class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()            # email или username
    password = serializers.CharField()
    remember_me = serializers.BooleanField(default=False)

    def validate(self, attrs):
        login = attrs["login"]
        password = attrs["password"]

        u = User.objects.filter(email=login).first()
        username = u.username if u else login
        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError({"detail": "Неверные учетные данные"})
        if not user.is_email_verified:
            raise serializers.ValidationError({"detail": "Email не подтвержден"})
        attrs["user"] = user
        return attrs

class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id","username","email","first_name","phone","company_name","photo",
                  "role","rating_as_customer","rating_as_carrier","is_email_verified")

class UpdateMeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name","phone","company_name","photo","role")

    def validate_role(self, value):
        if value not in (UserRole.LOGISTIC, UserRole.CUSTOMER, UserRole.CARRIER):
            raise serializers.ValidationError("Недопустимая роль")
        return value

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        email = self.validated_data["email"]
        user = User.objects.filter(email=email).first()
        if user:
            _, raw = EmailOTP.create_otp(user, EmailOTP.PURPOSE_RESET, ttl_min=15)
            send_code_email(user.email, raw, purpose="reset")
        return {"detail": "Если e-mail существует — код отправлен"}

class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code  = serializers.CharField(max_length=6)
    new_password = serializers.CharField()

    def validate(self, attrs):
        password_validation.validate_password(attrs["new_password"])
        return attrs

    def save(self, **kwargs):
        email = self.validated_data["email"]
        code  = self.validated_data["code"]
        newp  = self.validated_data["new_password"]
        user = User.objects.filter(email=email).first()
        if not user:
            raise serializers.ValidationError({"email": "Пользователь не найден"})
        otp = (EmailOTP.objects
               .filter(user=user, purpose=EmailOTP.PURPOSE_RESET, is_used=False)
               .order_by("-created_at").first())
        if not otp or not otp.check_and_consume(code):
            raise serializers.ValidationError({"code": "Неверный или просроченный код"})
        user.set_password(newp)
        user.save(update_fields=["password"])
        return {"detail": "Пароль обновлен"}