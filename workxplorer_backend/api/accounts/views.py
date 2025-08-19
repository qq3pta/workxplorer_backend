import random
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import User, EmailOTP
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    ProfileSerializer,
    ChangeRoleSerializer,
    ChangePasswordSerializer,
)

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        user = serializer.save()
        code = f"{random.randint(0, 999999):06d}"
        EmailOTP.objects.create(user=user, code=code)
        send_mail("Verify your email", f"Your code: {code}", None, [user.email])

class VerifyEmailView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email")
        code = request.data.get("code")
        user = User.objects.filter(email=email).first()
        otp = user and user.otps.filter(code=code, is_used=False).first()
        if not (user and otp):
            return Response({"detail": "Invalid code"}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = True
        user.save()
        otp.is_used = True
        otp.save()
        return Response({"detail": "Email verified"}, status=status.HTTP_200_OK)

class LoginView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def post(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        login, password = s.validated_data["login"], s.validated_data["password"]

        user = authenticate(request, username=login, password=password)
        if not user:
            u = User.objects.filter(email=login).first()
            if u:
                user = authenticate(request, username=u.username, password=password)

        if not user:
            return Response({"detail": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            return Response({"detail": "Email not verified"}, status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        return Response(
            {"access": str(refresh.access_token), "refresh": str(refresh)},
            status=status.HTTP_200_OK,
        )

class LogoutView(generics.GenericAPIView):
    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                token = RefreshToken(refresh)
                token.blacklist()
            except Exception:
                return Response({"detail": "Invalid refresh token"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            for t in OutstandingToken.objects.filter(user=request.user):
                BlacklistedToken.objects.get_or_create(token=t)
        return Response({"detail": "Logged out"}, status=status.HTTP_200_OK)

class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    def get_object(self):
        return self.request.user

class ChangeRoleView(generics.GenericAPIView):
    serializer_class = ChangeRoleSerializer
    def post(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        request.user.role = s.validated_data["role"]
        request.user.save()
        return Response({"detail": "Role changed", "role": request.user.role}, status=status.HTTP_200_OK)

class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer
    def post(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        if not request.user.check_password(s.validated_data["old_password"]):
            return Response({"detail": "Wrong old password"}, status=status.HTTP_400_BAD_REQUEST)
        request.user.set_password(s.validated_data["new_password"])
        request.user.save()
        return Response({"detail": "Password changed"}, status=status.HTTP_200_OK)