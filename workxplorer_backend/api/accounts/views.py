from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
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
from api.notifications.services import notify
from rest_framework_simplejwt.tokens import (
    BlacklistedToken,
    OutstandingToken,
    RefreshToken,
)


from .models import FleetMembership, Profile
from .permissions import IsAuthenticatedAndVerified
from .serializers import (
    AvatarUploadSerializer,
    DeleteAccountSerializer,
    ForgotPasswordSerializer,
    FleetInviteSerializer,
    FleetMembershipSerializer,
    FleetUserSerializer,
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


def _emit_fleet_event(user_ids, payload):
    channel_layer = get_channel_layer()
    for user_id in filter(None, user_ids):
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            to_ws_safe({"type": "notify", "data": payload}),
        )


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


@extend_schema(tags=["fleet"], responses=FleetUserSerializer(many=True))
class FleetCandidateListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        role = (request.query_params.get("role") or "CARRIER").upper()

        if role not in {"CARRIER", "LOGISTIC"}:
            return Response({"detail": "Invalid role."}, status=status.HTTP_400_BAD_REQUEST)

        relations = {
            item.member_id: item.status
            for item in FleetMembership.objects.filter(owner=request.user)
        }

        users = User.objects.filter(is_active=True, role=role).exclude(id=request.user.id)
        if query:
            users = users.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(company_name__icontains=query)
                | Q(phone__icontains=query)
                | Q(email__icontains=query)
            )

        users = users.order_by("first_name", "username", "id")[:50]
        data = FleetUserSerializer(users, many=True, context={"request": request}).data
        for item in data:
            item["fleet_status"] = relations.get(item["id"])
            item["is_sent"] = item["fleet_status"] == FleetMembership.Status.PENDING
            item["is_in_park"] = item["fleet_status"] == FleetMembership.Status.ACCEPTED

        return Response(data)


@extend_schema(tags=["fleet"], responses=FleetMembershipSerializer(many=True))
class FleetListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        status_param = request.query_params.get("status") or FleetMembership.Status.ACCEPTED
        qs = (
            FleetMembership.objects.filter(owner=request.user, status=status_param)
            .select_related("owner", "member")
            .order_by("member__role", "member__first_name", "member__username")
        )
        serializer = FleetMembershipSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)


@extend_schema(tags=["fleet"], request=FleetInviteSerializer, responses=FleetMembershipSerializer)
class FleetInviteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FleetInviteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        invitee = serializer.context["invitee"]
        membership = FleetMembership.objects.filter(owner=request.user, member=invitee).first()
        if membership and membership.status == FleetMembership.Status.ACCEPTED:
            data = FleetMembershipSerializer(membership, context={"request": request}).data
            return Response(data, status=status.HTTP_200_OK)

        if membership:
            membership.status = FleetMembership.Status.PENDING
            membership.responded_at = None
            membership.save(update_fields=["status", "responded_at", "updated_at"])
            created = False
        else:
            membership = FleetMembership.objects.create(owner=request.user, member=invitee)
            created = True

        owner_name = request.user.get_full_name() or request.user.username
        notify(
            user=invitee,
            type="fleet_invite",
            title="Vam otpravleno predlozhenie dobavit v park?",
            message="Vy mozhete prinyat libo otkazatsya ot predlozheniya.",
            payload={
                "membership_id": membership.id,
                "owner_id": request.user.id,
                "owner_name": owner_name,
                "event": "fleet_invite",
                "screen": "Notifications",
                "route": "/notifications",
            },
        )

        _emit_fleet_event(
            {request.user.id, invitee.id},
            {
                "event": "fleet_invite_sent",
                "membership_id": membership.id,
                "owner_id": request.user.id,
                "member_id": invitee.id,
                "status": membership.status,
            },
        )

        data = FleetMembershipSerializer(membership, context={"request": request}).data
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@extend_schema(tags=["fleet"], responses=FleetMembershipSerializer(many=True))
class FleetIncomingInviteListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            FleetMembership.objects.filter(
                member=request.user,
                status=FleetMembership.Status.PENDING,
            )
            .select_related("owner", "member")
            .order_by("-invited_at")
        )
        serializer = FleetMembershipSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)


class FleetInviteDecisionView(APIView):
    permission_classes = [IsAuthenticated]
    decision = None

    def post(self, request, pk):
        membership = (
            FleetMembership.objects.select_related("owner", "member")
            .filter(pk=pk, member=request.user)
            .first()
        )
        if not membership:
            return Response({"detail": "Invite not found."}, status=status.HTTP_404_NOT_FOUND)

        if membership.status != FleetMembership.Status.PENDING:
            return Response(
                {"detail": "Invite has already been processed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership.status = self.decision
        membership.responded_at = timezone.now()
        membership.save(update_fields=["status", "responded_at", "updated_at"])

        event = (
            "fleet_invite_accepted"
            if self.decision == FleetMembership.Status.ACCEPTED
            else "fleet_invite_declined"
        )
        _emit_fleet_event(
            {membership.owner_id, membership.member_id},
            {
                "event": event,
                "membership_id": membership.id,
                "owner_id": membership.owner_id,
                "member_id": membership.member_id,
                "status": membership.status,
            },
        )

        serializer = FleetMembershipSerializer(membership, context={"request": request})
        return Response(serializer.data)


class FleetInviteAcceptView(FleetInviteDecisionView):
    decision = FleetMembership.Status.ACCEPTED


class FleetInviteDeclineView(FleetInviteDecisionView):
    decision = FleetMembership.Status.DECLINED


class FleetMembershipDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        membership = FleetMembership.objects.filter(owner=request.user, pk=pk).first()
        if not membership:
            return Response({"detail": "Fleet member not found."}, status=status.HTTP_404_NOT_FOUND)

        owner_id = membership.owner_id
        member_id = membership.member_id
        membership.delete()

        _emit_fleet_event(
            {owner_id, member_id},
            {
                "event": "fleet_member_removed",
                "membership_id": pk,
                "owner_id": owner_id,
                "member_id": member_id,
            },
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


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
    tags=["auth"],
    request=DeleteAccountSerializer,
    responses=inline_serializer(
        "DeleteAccountResponse",
        {"detail": serializers.CharField()},
    ),
)
class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeleteAccountSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        self._deactivate_account(request.user)
        _notify_dashboard()
        return Response({"detail": "Аккаунт удалён"}, status=status.HTTP_200_OK)

    def delete(self, request):
        return self.post(request)

    def _deactivate_account(self, user):
        deleted_username = f"deleted_user_{user.id}"

        with transaction.atomic():
            try:
                if user.photo:
                    user.photo.delete(save=False)
            except Exception:
                pass

            for token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=token)

            user.email = None
            user.phone = None
            user.username = deleted_username
            user.first_name = ""
            user.last_name = ""
            user.company_name = ""
            user.inn = ""
            user.legal_address = ""
            user.photo = None
            user.fcm_token = None
            user.is_active = False
            user.is_verified = False
            user.is_email_verified = False
            user.is_phone_verified = False
            user.is_accept_policy = False
            user.policy_accepted_at = None
            user.last_seen = None
            user.set_unusable_password()
            user.save(
                update_fields=[
                    "email",
                    "phone",
                    "username",
                    "first_name",
                    "last_name",
                    "company_name",
                    "inn",
                    "legal_address",
                    "photo",
                    "fcm_token",
                    "is_active",
                    "is_verified",
                    "is_email_verified",
                    "is_phone_verified",
                    "is_accept_policy",
                    "policy_accepted_at",
                    "last_seen",
                    "password",
                ]
            )

            user.otps.all().delete()

            if hasattr(user, "profile"):
                user.profile.country = ""
                user.profile.country_code = ""
                user.profile.region = ""
                user.profile.city = ""
                user.profile.save(update_fields=["country", "country_code", "region", "city"])

            try:
                user.push_devices.update(
                    is_active=False,
                    error="Account deleted",
                    disabled_at=timezone.now(),
                )
            except Exception:
                pass


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
