from datetime import timedelta
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model

from .serializers import (
    RegisterSerializer, VerifyEmailSerializer, ResendVerifySerializer,
    LoginSerializer, MeSerializer, UpdateMeSerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer,
)
from .permissions import IsAuthenticatedAndVerified

User = get_user_model()

def issue_tokens(user, remember: bool):
    refresh = RefreshToken.for_user(user)
    if remember:
        refresh.set_exp(lifetime=timedelta(days=30))
    return {"access": str(refresh.access_token), "refresh": str(refresh)}

class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    def create(self, request, *args, **kwargs):
        super().create(request, *args, **kwargs)
        return Response({"detail": "Регистрация успешна. Проверьте почту."},
                        status=status.HTTP_201_CREATED)

class ResendVerifyView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        s = ResendVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())

class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        s = VerifyEmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        return Response({"detail": "E-mail подтвержден", **issue_tokens(user, remember=False)})

class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.validated_data["user"]
        remember = s.validated_data["remember_me"]
        return Response({"user": MeSerializer(user).data, **issue_tokens(user, remember)})

class MeView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = MeSerializer
    def get_object(self):
        return self.request.user

class UpdateMeView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = UpdateMeSerializer
    def get_object(self):
        return self.request.user

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        s = ForgotPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        s = ResetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())