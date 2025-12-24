from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers
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


@extend_schema(
    tags=["auth"],
    request=RegisterSerializer,
    responses=inline_serializer("RegisterResponse", {"detail": serializers.CharField()}),
)
class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response({"detail": "Регистрация успешна."}, status=201)


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

        if user.is_email_verified:
            return Response({"detail": "E-mail уже подтвержден"}, status=200)

        user.is_email_verified = True
        user.is_active = True
        user.save(update_fields=["is_email_verified", "is_active"])

        return Response(
            {"detail": "E-mail подтвержден", **issue_tokens(user, remember=False)}, status=200
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
        remember = s.validated_data.get("remember_me")

        fcm = request.data.get("fcm_token")
        if fcm:
            user.fcm_token = fcm
            user.save(update_fields=["fcm_token"])

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
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_str = request.data.get("refresh")
        remember = bool(request.data.get("remember_me", False))
        if not refresh_str:
            return Response({"detail": "refresh токен обязателен"}, status=400)

        try:
            old = RefreshToken(refresh_str)
            user = User.objects.get(id=old["user_id"])
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
        partial = kwargs.pop("partial", True)
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        Profile.objects.get_or_create(user=instance)
        return Response(MeSerializer(instance).data)


@extend_schema(
    tags=["auth"],
    request=inline_serializer("FCMUpdateRequest", {"fcm_token": serializers.CharField()}),
    responses=inline_serializer("FCMUpdateResponse", {"detail": serializers.CharField()}),
)
class UpdateFCMTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("fcm_token")
        if not token:
            return Response({"detail": "fcm_token обязателен"}, status=400)

        request.user.fcm_token = token
        request.user.save(update_fields=["fcm_token"])

        return Response({"detail": "FCM токен обновлён"})


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


@extend_schema(
    tags=["auth"],
    responses=AnalyticsSerializer,
)
class AnalyticsView(APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        user = request.user
        now = timezone.now()

        qs = Order.objects.filter(status=Order.OrderStatus.DELIVERED)

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

        registered_since = getattr(user, "date_joined", now).date()
        days_since_registered = (now.date() - registered_since).days

        agg = qs.aggregate(total_km=Sum("route_distance_km"))
        distance_km = float(agg["total_km"] or 0)
        deals_count = qs.count()

        # ---------- BAR CHART ----------
        year = int(request.query_params.get("year", now.year))
        half = request.query_params.get("half", "1")  # "1" | "2"

        months = range(1, 7) if half == "1" else range(7, 13)

        def month_label(m):
            return [
                "",
                "Янв",
                "Фев",
                "Мар",
                "Апр",
                "Май",
                "Июн",
                "Июл",
                "Авг",
                "Сен",
                "Окт",
                "Ноя",
                "Дек",
            ][m]

        base_qs = Order.objects.filter(
            created_at__year=year,
            created_at__month__in=months,
            status=Order.OrderStatus.DELIVERED,
        )

        by_month = base_qs.annotate(m=TruncMonth("created_at")).values("m")

        def sums(qs):
            return {r["m"].month: float(r["s"] or 0) for r in qs.annotate(s=Sum("price_total"))}

        given_map = sums(by_month.filter(customer=user))
        received_map = sums(by_month.filter(carrier=user))
        earned_map = sums(by_month.filter(logistic=user))

        bar_chart = {
            "labels": [month_label(m) for m in months],
            "given": [given_map.get(m, 0) for m in months],
            "received": [received_map.get(m, 0) for m in months],
            "earned": [earned_map.get(m, 0) for m in months],
        }

        data = {
            "successful_deliveries": current_cnt,
            "successful_deliveries_change": round(successful_change, 3),
            "registered_since": registered_since,
            "days_since_registered": days_since_registered,
            "rating": float(rating or 0),
            "distance_km": distance_km,
            "deals_count": deals_count,
            "bar_chart": bar_chart,
        }

        ser = AnalyticsSerializer(data=data)
        ser.is_valid(raise_exception=True)
        return Response(ser.data)
