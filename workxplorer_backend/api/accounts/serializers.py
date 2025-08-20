from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import User, UserRole


class RegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
        validators=[UniqueValidator(User.objects.all(), message="Email уже используется")]
    )
    username = serializers.CharField(
        validators=[UniqueValidator(User.objects.all(), message="Логин уже используется")]
    )
    phone = serializers.CharField(
        validators=[UniqueValidator(User.objects.all(), message="Телефон уже используется")]
    )

    class Meta:
        model = User
        fields = ("username", "email", "phone", "company_name", "password")
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        user = User(
            username=validated_data["username"],
            email=validated_data["email"],
            phone=validated_data["phone"],
            company_name=validated_data.get("company_name", ""),
            role=UserRole.LOGISTIC,  # стартовая роль — логист
            is_active=False,         # активируется после подтверждения email
        )
        user.set_password(validated_data["password"])
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField(write_only=True)


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)


class LogoutSerializer(serializers.Serializer):
    # если refresh не передан — разлогиним все токены пользователя
    refresh = serializers.CharField(required=False, allow_blank=True)


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        read_only_fields = (
            "username",
            "email",
            "rating_as_customer",
            "rating_as_carrier",
            "role",
        )
        fields = (
            "id",
            "photo",
            "username",
            "company_name",
            "role",
            "email",
            "phone",
            "rating_as_customer",
            "rating_as_carrier",
        )


class ChangeRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=UserRole.choices)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value