from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from common.ws_utils import to_ws_safe
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from api.loads.models import Cargo
from rest_framework_simplejwt.tokens import (
    BlacklistedToken,
    OutstandingToken,
    RefreshToken,
)


from .models import Profile
from .permissions import IsAuthenticatedAndVerified
from .serializers import (
    AvatarUploadSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    MeSerializer,
    RegisterSerializer,
    ResendVerifySerializer,
    ChangePasswordSerializer,
    RoleChangeSerializer,
    SendPhoneOTPSerializer,
    UpdateMeSerializer,
    VerifyEmailSerializer,
    VerifyPhoneOTPSerializer,
    SendEmailVerifyFromProfileSerializer,
    VerifyEmailFromProfileSerializer,
)

User = get_user_model()


def _notify_dashboard(event="dashboard_updated"):
    channel_layer = get_channel_layer()

    five_minutes_ago = timezone.now() - timedelta(minutes=5)

    payload = {
        "total_users": User.objects.count(),
        "online_users": User.objects.filter(last_seen__gte=five_minutes_ago).count(),
        "total_cargos": Cargo.objects.count(),
    }

    async_to_sync(channel_layer.group_send)(
        "dashboard",
        to_ws_safe(
            {
                "type": "notify",
                "data": {
                    "event": event,
                    "stats": payload,
                },
            }
        ),
    )


def _notify_analytics(user_id, event="analytics_updated"):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        to_ws_safe(
            {
                "type": "notify",
                "data": {
                    "event": event,
                },
            }
        ),
    )


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
        _notify_dashboard()
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
        _notify_dashboard()
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

        _notify_dashboard()
        return Response({"detail": "Вы вышли из системы"})


@extend_schema(tags=["auth"], responses=MeSerializer)
class MeView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
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
    permission_classes = [IsAuthenticated]
    serializer_class = UpdateMeSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

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
    request=ChangePasswordSerializer,
    responses=inline_serializer(
        "ChangePasswordResponse",
        {"detail": serializers.CharField()},
    ),
)
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.save())


@extend_schema(
    tags=["dashboard"],
    responses=inline_serializer(
        "DashboardStatsResponse",
        {
            "total_users": serializers.IntegerField(),
            "online_users": serializers.IntegerField(),
            "total_cargos": serializers.IntegerField(),
        },
    ),
)
@api_view(["GET"])
def dashboard_stats(request):
    total_users = User.objects.count()

    five_minutes_ago = timezone.now() - timedelta(minutes=5)
    online_users = User.objects.filter(last_seen__gte=five_minutes_ago).count()

    total_cargos = Cargo.objects.count()

    return Response(
        {
            "total_users": total_users,
            "online_users": online_users,
            "total_cargos": total_cargos,
        }
    )


@extend_schema(
    tags=["auth"],
    request=SendEmailVerifyFromProfileSerializer,
    responses=inline_serializer(
        "SendEmailVerifyFromProfileResponse",
        {
            "detail": serializers.CharField(),
            "seconds_left": serializers.IntegerField(),
        },
    ),
)
class SendEmailVerifyFromProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = SendEmailVerifyFromProfileSerializer(
            data=request.data,
            context={"request": request},
        )
        s.is_valid(raise_exception=True)
        return Response(s.save())


@extend_schema(
    tags=["auth"],
    request=inline_serializer(
        "VerifyEmailFromProfileRequest",
        {
            "code": serializers.CharField(),
        },
    ),
    responses=inline_serializer(
        "VerifyEmailFromProfileResponse",
        {
            "detail": serializers.CharField(),
        },
    ),
)
class VerifyEmailFromProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = VerifyEmailFromProfileSerializer(
            data=request.data,
            context={"request": request},
        )
        s.is_valid(raise_exception=True)
        return Response(s.save())


@extend_schema(
    tags=["auth"],
    request={"multipart/form-data": AvatarUploadSerializer},
    responses=MeSerializer,
)
class AvatarView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        s = AvatarUploadSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        user = s.save()
        return Response(MeSerializer(user).data, status=status.HTTP_200_OK)

    def delete(self, request):
        user = request.user
        if user.photo:
            try:
                user.photo.delete(save=False)
            except Exception:
                pass
            user.photo = None
            user.save(update_fields=["photo"])
        return Response(status=status.HTTP_204_NO_CONTENT)
