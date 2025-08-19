from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User, UserRole

class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username","email","phone","company_name","password")
        extra_kwargs = {"password": {"write_only": True}}
    def create(self, data):
        user = User(
            username=data["username"],
            email=data["email"],
            phone=data["phone"],
            company_name=data.get("company_name",""),
            role=UserRole.LOGISTIC,
            is_active=False,
        )
        user.set_password(data["password"])
        user.save()
        return user

class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField(write_only=True)

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        read_only_fields = ("username","email","rating_as_customer","rating_as_carrier","role")
        fields = ("id","photo","username","company_name","role","email","phone","rating_as_customer","rating_as_carrier")

class ChangeRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=UserRole.choices)

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    def validate_new_password(self, value):
        validate_password(value); return value