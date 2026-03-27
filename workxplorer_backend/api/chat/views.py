from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Chat, ChatParticipant
from .serializers import (
    ChatListItemSerializer,
    ChatSummarySerializer,
    GroupCreateSerializer,
    InviteLinkRequestSerializer,
    InviteLinkResponseSerializer,
    JoinByLinkSerializer,
    MarkReadSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    UserSearchResultSerializer,
)
from .services import user_can_manage_group, user_is_chat_participant

User = get_user_model()


class ErrorDetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ChatPingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={
            200: inline_serializer(
                "ChatPingResponse",
                {
                    "status": serializers.CharField(),
                    "service": serializers.CharField(),
                },
            )
        },
    )
    def get(self, request):
        return Response({"status": "ok", "service": "chat"})


class GroupCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=GroupCreateSerializer,
        responses={201: ChatSummarySerializer, 400: ErrorDetailSerializer},
    )
    def post(self, request):
        serializer = GroupCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        chat = serializer.save()
        return Response(ChatSummarySerializer(chat).data, status=201)


class GroupInviteLinkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=InviteLinkRequestSerializer,
        responses={
            200: InviteLinkResponseSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, chat_id: int):
        try:
            chat = Chat.objects.get(pk=chat_id)
        except Chat.DoesNotExist:
            return Response({"detail": "Чат не найден."}, status=404)

        if not user_is_chat_participant(chat, request.user.id):
            return Response({"detail": "Нет доступа к чату."}, status=403)

        if not user_can_manage_group(chat, request.user.id):
            return Response(
                {"detail": "Недостаточно прав для управления групповым чатом."}, status=403
            )

        serializer = InviteLinkRequestSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        chat.refresh_invite(expires_in_hours=serializer.validated_data["expires_in_hours"])

        response = InviteLinkResponseSerializer(
            {"token": chat.invite_token, "expires_at": chat.invite_expires_at}
        )
        return Response(response.data)


class JoinByLinkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=JoinByLinkSerializer,
        responses={
            200: ChatSummarySerializer,
            400: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
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

    @extend_schema(
        tags=["chat"],
        parameters=[
            OpenApiParameter(
                name="q",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Поисковая строка (минимум 2 символа).",
                required=True,
            )
        ],
        responses={200: UserSearchResultSerializer(many=True)},
    )
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


class ChatListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={200: ChatListItemSerializer(many=True)},
    )
    def get(self, request):
        participant_qs = (
            ChatParticipant.objects.filter(user=request.user, is_active=True)
            .select_related("chat")
            .order_by("-chat__last_message_at")
        )
        chats = []
        for participant in participant_qs:
            chat = participant.chat
            chat._viewer_participant = participant
            chats.append(chat)
        return Response(ChatListItemSerializer(chats, many=True, context={"request": request}).data)


class ChatMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get_chat_and_participant(self, user, chat_id):
        try:
            participant = ChatParticipant.objects.select_related("chat").get(
                chat_id=chat_id, user=user, is_active=True
            )
        except ChatParticipant.DoesNotExist:
            return None, None
        return participant.chat, participant

    @extend_schema(
        tags=["chat"],
        responses={200: MessageSerializer(many=True), 404: ErrorDetailSerializer},
    )
    def get(self, request, chat_id: int):
        chat, participant = self.get_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)

        messages = chat.messages.select_related("sender").order_by("created_at")
        participant.last_read_at = timezone.now()
        participant.save(update_fields=["last_read_at"])
        return Response(MessageSerializer(messages, many=True).data)

    @extend_schema(
        tags=["chat"],
        request=MessageCreateSerializer,
        responses={201: MessageSerializer, 404: ErrorDetailSerializer},
    )
    def post(self, request, chat_id: int):
        chat, _participant = self.get_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)

        serializer = MessageCreateSerializer(
            data=request.data, context={"request": request, "chat": chat}
        )
        serializer.is_valid(raise_exception=True)
        msg = serializer.save()
        return Response(MessageSerializer(msg).data, status=201)


class ChatReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=MarkReadSerializer,
        responses={
            200: inline_serializer(
                "ChatReadResponse",
                {"last_read_at": serializers.DateTimeField(allow_null=True)},
            ),
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, chat_id: int):
        try:
            participant = ChatParticipant.objects.select_related("chat").get(
                chat_id=chat_id, user=request.user, is_active=True
            )
        except ChatParticipant.DoesNotExist:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)

        serializer = MarkReadSerializer(
            data=request.data or {},
            context={"chat": participant.chat, "participant": participant},
        )
        serializer.is_valid(raise_exception=True)
        payload = serializer.save()
        return Response(payload)
