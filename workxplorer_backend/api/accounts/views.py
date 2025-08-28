from datetime import timedelta
from django.conf import settings

from django.contrib.auth import get_user_model
from rest_framework import generics, status, serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import (
    RefreshToken,
    OutstandingToken,
    BlacklistedToken,
)

from drf_spectacular.utils import extend_schema, inline_serializer

from .permissions import IsAuthenticatedAndVerified
from .serializers import (
    RegisterSerializer,
    VerifyEmailSerializer,
    ResendVerifySerializer,
    LoginSerializer,
    MeSerializer,
    UpdateMeSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    RoleChangeSerializer,
)

User = get_user_model()


def issue_tokens(user, remember: bool):
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token

    base_access = settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]
    if remember:
        refresh.set_exp(lifetime=timedelta(days=30))
        access.set_exp(lifetime=timedelta(hours=12))
    else:
        access.set_exp(lifetime=base_access)

    return {"access": str(access), "refresh": str(refresh)}


@extend_schema(
    tags=["auth"],
    request=RegisterSerializer,
    responses=inline_serializer("RegisterResponse", {"detail": serializers.CharField()}),
)
class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        super().create(request, *args, **kwargs)
        return Response(
            {"detail": "Регистрация успешна. Проверьте почту."},
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["auth"],
    request=ResendVerifySerializer,
    responses=inline_serializer("ResendVerifyResponse", {"detail": serializers.CharField()}),
)
class ResendVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = ResendVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())


@extend_schema(
    tags=["auth"],
    request=VerifyEmailSerializer,
    responses=inline_serializer(
        "VerifyEmailResponse",
        {
            "detail": serializers.CharField(),
            "access": serializers.CharField(),
            "refresh": serializers.CharField(),
        },
    ),
)
class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = VerifyEmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        return Response(
            {"detail": "E-mail подтвержден", **issue_tokens(user, remember=False)}
        )


@extend_schema(
    tags=["auth"],
    request=LoginSerializer,
    responses=inline_serializer(
        "LoginResponse",
        {
            "user": MeSerializer(),
            "access": serializers.CharField(),
            "refresh": serializers.CharField(),
        },
    ),
)
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.validated_data["user"]
        remember = s.validated_data["remember_me"]
        return Response({"user": MeSerializer(user).data, **issue_tokens(user, remember)})


@extend_schema(
    tags=["auth"],
    request=inline_serializer(
        "TokenRefreshRequest",
        {
            "refresh": serializers.CharField(),
            "remember_me": serializers.BooleanField(required=False),
        },
    ),
    responses=inline_serializer(
        "TokenRefreshResponse",
        {"access": serializers.CharField(), "refresh": serializers.CharField()},
    ),
)
class RefreshView(APIView):
    """
    Обновление токенов вручную (альтернатива стандартному TokenRefreshView),
    с опциональной ротацией под remember_me.
    Body: {"refresh": "<token>", "remember_me": true|false}
    """
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_str = request.data.get("refresh")
        remember = bool(request.data.get("remember_me", False))
        if not refresh_str:
            return Response({"detail": "refresh токен обязателен"}, status=400)

        try:
            old = RefreshToken(refresh_str)
            user_id = old["user_id"]
            user = User.objects.get(id=user_id)

            try:
                old.blacklist()
            except Exception:
                pass

            return Response(issue_tokens(user, remember))
        except Exception:
            return Response({"detail": "Невалидный refresh токен"}, status=401)


@extend_schema(
    tags=["auth"],
    request=inline_serializer(
        "LogoutRequest",
        {"refresh": serializers.CharField(required=False)},
    ),
    responses=inline_serializer(
        "LogoutResponse",
        {"detail": serializers.CharField()},
    ),
)
class LogoutView(APIView):
    """
    POST /api/auth/logout
    - с телом {"refresh": "<token>"}: выход только с текущего устройства
    - без тела: выход со всех устройств
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_str = request.data.get("refresh")
        if refresh_str:
            try:
                RefreshToken(refresh_str).blacklist()
            except Exception:
                pass
        else:
            for t in OutstandingToken.objects.filter(user=request.user):
                BlacklistedToken.objects.get_or_create(token=t)
        return Response({"detail": "Вы вышли из системы"})


@extend_schema(tags=["auth"], responses=MeSerializer)
class MeView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


@extend_schema(
    tags=["auth"],
    request=UpdateMeSerializer,
    responses=MeSerializer,
)
class UpdateMeView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = UpdateMeSerializer

    def get_object(self):
        return self.request.user


@extend_schema(
    tags=["auth"],
    request=RoleChangeSerializer,
    responses=inline_serializer(
        "RoleChangeResponse",
        {"detail": serializers.CharField(), "role": serializers.CharField(required=False)},
    ),
)
class ChangeRoleView(APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def post(self, request):
        s = RoleChangeSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        return Response(s.save())


@extend_schema(
    tags=["auth"],
    request=ForgotPasswordSerializer,
    responses=inline_serializer("ForgotPasswordResponse", {"detail": serializers.CharField()}),
)
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = ForgotPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())


@extend_schema(
    tags=["auth"],
    request=ResetPasswordSerializer,
    responses=inline_serializer("ResetPasswordResponse", {"detail": serializers.CharField()}),
)
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = ResetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())