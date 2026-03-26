from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import Chat, ChatParticipant
from .serializers import (
    ChatSummarySerializer,
    GroupCreateSerializer,
    InviteLinkRequestSerializer,
    InviteLinkResponseSerializer,
    JoinByLinkSerializer,
    UserSearchResultSerializer,
)
from .services import user_can_manage_group, user_is_chat_participant

User = get_user_model()


class ChatPingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"status": "ok", "service": "chat"})


class GroupCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GroupCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        chat = serializer.save()
        return Response(ChatSummarySerializer(chat).data, status=201)


class GroupInviteLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_id: int):
        try:
            chat = Chat.objects.get(pk=chat_id)
        except Chat.DoesNotExist:
            return Response({"detail": "Чат не найден."}, status=404)

        if not user_is_chat_participant(chat, request.user.id):
            return Response({"detail": "Нет доступа к чату."}, status=403)

        if not user_can_manage_group(chat, request.user.id):
            return Response({"detail": "Недостаточно прав для управления групповым чатом."}, status=403)

        serializer = InviteLinkRequestSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        chat.refresh_invite(expires_in_hours=serializer.validated_data["expires_in_hours"])

        response = InviteLinkResponseSerializer(
            {"token": chat.invite_token, "expires_at": chat.invite_expires_at}
        )
        return Response(response.data)


class JoinByLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = JoinByLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]

        try:
            chat = Chat.objects.get(invite_token=token, chat_type=Chat.ChatType.GROUP)
        except Chat.DoesNotExist:
            return Response({"detail": "Ссылка недействительна."}, status=404)

        if not chat.is_invite_active:
            return Response({"detail": "Срок действия ссылки истёк или она отключена."}, status=400)

        participant, created = ChatParticipant.objects.get_or_create(
            chat=chat,
            user=request.user,
            defaults={"is_active": True, "is_admin": False},
        )
        if not created and not participant.is_active:
            participant.is_active = True
            participant.save(update_fields=["is_active"])

        return Response(ChatSummarySerializer(chat).data, status=200)


class UserSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response([])

        qs = (
            User.objects.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
                | Q(company_name__icontains=q)
            )
            .exclude(id=request.user.id)
            .order_by("first_name", "last_name", "username")[:20]
        )
        return Response(UserSearchResultSerializer(qs, many=True).data)
