from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import (
    BlacklistedToken,
    OutstandingToken,
    RefreshToken,
)

from api.orders.models import Order

from .models import Profile, UserRole
from .permissions import IsAuthenticatedAndVerified
from .serializers import (
    AnalyticsSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    MeSerializer,
    RegisterSerializer,
    ResendVerifySerializer,
    ResetPasswordSerializer,
    RoleChangeSerializer,
    SendPhoneOTPSerializer,
    UpdateMeSerializer,
    VerifyEmailSerializer,
    VerifyPhoneOTPSerializer,
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


# ===================== WhatsApp-OTP (телефон) =====================


@extend_schema(
    tags=["auth"],
    request=SendPhoneOTPSerializer,
    responses=inline_serializer(
        "SendPhoneOTPResponse",
        {"detail": serializers.CharField(), "seconds_left": serializers.IntegerField()},
    ),
)
class SendPhoneOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = SendPhoneOTPSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())


@extend_schema(
    tags=["auth"],
    request=VerifyPhoneOTPSerializer,
    responses=inline_serializer(
        "VerifyPhoneOTPResponse",
        {"verified": serializers.BooleanField()},
    ),
)
class VerifyPhoneOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = VerifyPhoneOTPSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(s.save())


# ===================== Регистрация / E-mail =====================


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
            {"detail": "Регистрация успешна."},
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
        Profile.objects.get_or_create(user=user)
        return Response({"detail": "E-mail подтвержден", **issue_tokens(user, remember=False)})


# ===================== Логин / Токены / Выход =====================


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
        Profile.objects.get_or_create(user=user)
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


# ===================== Профиль =====================


@extend_schema(tags=["auth"], responses=MeSerializer)
class MeView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = MeSerializer

    def get_object(self):
        Profile.objects.get_or_create(user=self.request.user)
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

    def update(self, request, *args, **kwargs):
        """
        Возвращаем MeSerializer после успешного обновления,
        чтобы фронт сразу получил вложенный profile.
        """
        partial = kwargs.pop("partial", True)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        Profile.objects.get_or_create(user=instance)
        return Response(MeSerializer(instance).data)


# ===================== Роли =====================


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


# ===================== Сброс пароля по e-mail =====================


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


# ===================== Аналитика профиля =====================


@extend_schema(
    tags=["auth"],
    responses=AnalyticsSerializer,
)
class AnalyticsView(APIView):
    """
    GET /api/auth/me/analytics/ — данные для карточек аналитики в профиле.
    """

    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        user = request.user
        now = timezone.now()

        # Базовый queryset успешных перевозок
        qs = Order.objects.filter(status=Order.OrderStatus.DELIVERED)

        # Фильтрация по роли
        role = getattr(user, "role", None)
        if role == UserRole.LOGISTIC:
            qs = qs.filter(customer=user)
            rating = user.rating_as_customer or 0
        elif role == UserRole.CARRIER:
            qs = qs.filter(carrier=user)
            rating = user.rating_as_carrier or 0
        else:
            qs = qs.filter(Q(customer=user) | Q(carrier=user))
            rating = user.rating_as_customer or user.rating_as_carrier or 0

        # Текущий и предыдущий 30-дневные периоды
        days = 30
        current_start = now - timedelta(days=days)
        prev_start = now - timedelta(days=days * 2)

        current_qs = qs.filter(created_at__gte=current_start)
        prev_qs = qs.filter(created_at__gte=prev_start, created_at__lt=current_start)

        current_cnt = current_qs.count()
        prev_cnt = prev_qs.count()

        if prev_cnt > 0:
            successful_change = (current_cnt - prev_cnt) / prev_cnt
        else:
            successful_change = 1.0 if current_cnt > 0 else 0.0

        # Регистрация
        registered_since = getattr(user, "date_joined", now).date()
        days_since_registered = (now.date() - registered_since).days

        # Пройденное расстояние и количество сделок
        agg = qs.aggregate(total_km=Sum("route_distance_km"))
        distance_km = float(agg["total_km"] or 0)
        deals_count = qs.count()

        data = {
            "successful_deliveries": current_cnt,
            "successful_deliveries_change": round(successful_change, 3),
            "registered_since": registered_since,
            "days_since_registered": days_since_registered,
            "rating": float(rating or 0),
            "distance_km": distance_km,
            "deals_count": deals_count,
        }

        ser = AnalyticsSerializer(data=data)
        ser.is_valid(raise_exception=True)
        return Response(ser.data)
