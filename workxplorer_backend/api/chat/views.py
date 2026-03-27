from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Chat, ChatParticipant
from .serializers import (
    ChatInfoSerializer,
    ChatListItemSerializer,
    ChatSummarySerializer,
    GroupAddParticipantsSerializer,
    GroupCreateSerializer,
    InviteLinkRequestSerializer,
    InviteLinkResponseSerializer,
    JoinByLinkSerializer,
    MarkReadSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    OpenPersonalChatSerializer,
    UserSearchResultSerializer,
)
from .services import (
    emit_added_to_group,
    emit_chat_removed,
    emit_group_deleted,
    emit_member_joined,
    emit_member_left,
    emit_message_read,
    emit_new_message,
    sync_user_default_role_chat,
    user_can_manage_group,
    user_is_chat_participant,
)

User = get_user_model()


class ErrorDetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


def resolve_chat_and_participant(user, chat_identifier: str):
    chat_id_str = str(chat_identifier).strip()

    if chat_id_str.isdigit():
        try:
            participant = ChatParticipant.objects.select_related("chat").get(
                chat_id=int(chat_id_str), user=user, is_active=True
            )
            return participant.chat, participant
        except ChatParticipant.DoesNotExist:
            return None, None

    target_slug = slugify(chat_id_str)
    participants = ChatParticipant.objects.select_related("chat").filter(user=user, is_active=True)
    for participant in participants:
        if slugify(participant.chat.title or "") == target_slug:
            return participant.chat, participant

    return None, None


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
        added_user_ids = list(
            chat.participants.exclude(user_id=request.user.id).values_list("user_id", flat=True)
        )
        emit_added_to_group(chat, added_user_ids, added_by_id=request.user.id)
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
    def post(self, request, chat_id: str):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
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


class GroupAddParticipantsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=GroupAddParticipantsSerializer,
        responses={
            200: inline_serializer(
                "GroupAddParticipantsResponse",
                {
                    "chat": ChatSummarySerializer(),
                    "added_user_ids": serializers.ListField(child=serializers.IntegerField()),
                },
            ),
            400: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, chat_id: str):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден."}, status=404)
        if chat.chat_type != Chat.ChatType.GROUP:
            return Response(
                {"detail": "Добавлять участников можно только в групповой чат."}, status=400
            )
        if not user_can_manage_group(chat, request.user.id):
            return Response(
                {"detail": "Недостаточно прав для управления групповым чатом."}, status=403
            )

        serializer = GroupAddParticipantsSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        participant_ids = serializer.validated_data["participant_ids"]

        users_qs = User.objects.filter(id__in=participant_ids).exclude(id=request.user.id)
        found_ids = set(users_qs.values_list("id", flat=True))
        missing = [uid for uid in participant_ids if uid not in found_ids]
        if missing:
            return Response({"detail": f"Пользователи не найдены: {missing}"}, status=400)

        added_user_ids: list[int] = []
        for user in users_qs:
            participant, created = ChatParticipant.objects.get_or_create(
                chat=chat,
                user=user,
                defaults={"is_active": True, "is_admin": False},
            )
            if created:
                added_user_ids.append(user.id)
                continue

            if not participant.is_active:
                participant.is_active = True
                participant.save(update_fields=["is_active"])
                added_user_ids.append(user.id)

        if added_user_ids:
            emit_added_to_group(chat, added_user_ids, added_by_id=request.user.id)
            for user_id in added_user_ids:
                emit_member_joined(chat, user_id)

        return Response(
            {"chat": ChatSummarySerializer(chat).data, "added_user_ids": added_user_ids}
        )


class GroupLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={204: None, 400: ErrorDetailSerializer, 404: ErrorDetailSerializer},
    )
    def post(self, request, chat_id: str):
        chat, participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat or not participant:
            return Response({"detail": "Чат не найден."}, status=404)
        if chat.chat_type != Chat.ChatType.GROUP:
            return Response({"detail": "Покинуть можно только групповой чат."}, status=400)
        if chat.created_by_id == request.user.id:
            return Response(
                {"detail": "Владелец не может покинуть группу. Удалите группу целиком."}, status=400
            )

        participant.is_active = False
        participant.is_admin = False
        participant.save(update_fields=["is_active", "is_admin"])

        emit_member_left(chat.id, request.user.id)
        emit_chat_removed(request.user.id, chat.id, reason="left_group")
        return Response(status=204)


class PersonalChatDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={204: None, 400: ErrorDetailSerializer, 404: ErrorDetailSerializer},
    )
    def delete(self, request, chat_id: str):
        chat, participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat or not participant:
            return Response({"detail": "Чат не найден."}, status=404)
        if chat.chat_type != Chat.ChatType.PERSONAL:
            return Response({"detail": "Удалять этим методом можно только личный чат."}, status=400)

        participant.is_active = False
        participant.save(update_fields=["is_active"])
        emit_chat_removed(request.user.id, chat.id, reason="personal_deleted")
        return Response(status=204)


class GroupDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={204: None, 403: ErrorDetailSerializer, 404: ErrorDetailSerializer},
    )
    def delete(self, request, chat_id: str):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден."}, status=404)
        if chat.chat_type != Chat.ChatType.GROUP:
            return Response({"detail": "Удалять этим методом можно только группу."}, status=404)
        if chat.created_by_id != request.user.id:
            return Response({"detail": "Удалить группу может только владелец."}, status=403)

        user_ids = list(chat.participants.filter(is_active=True).values_list("user_id", flat=True))
        chat_id_int = chat.id
        title = chat.title
        chat.delete()

        emit_group_deleted(user_ids, chat_id_int, title=title, deleted_by_id=request.user.id)
        for user_id in user_ids:
            emit_chat_removed(user_id, chat_id_int, reason="group_deleted")

        return Response(status=204)


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
        became_active = False
        if not created and not participant.is_active:
            participant.is_active = True
            participant.save(update_fields=["is_active"])
            became_active = True

        if created or became_active:
            emit_added_to_group(chat, [request.user.id], added_by_id=None)
            emit_member_joined(chat, request.user.id)

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
        return Response(
            UserSearchResultSerializer(qs, many=True, context={"request": request}).data
        )


class OpenPersonalChatView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=OpenPersonalChatSerializer,
        responses={
            200: inline_serializer(
                "OpenPersonalChatResponse",
                {
                    "created": serializers.BooleanField(),
                    "chat": ChatInfoSerializer(),
                },
            ),
            201: inline_serializer(
                "OpenPersonalChatCreatedResponse",
                {
                    "created": serializers.BooleanField(),
                    "chat": ChatInfoSerializer(),
                },
            ),
            400: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        serializer = OpenPersonalChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_user_id = serializer.validated_data["user_id"]
        target_user = User.objects.filter(id=target_user_id).first()
        if not target_user:
            return Response({"detail": "Пользователь не найден."}, status=404)
        if target_user.id == request.user.id:
            return Response({"detail": "Нельзя создать личный чат с самим собой."}, status=400)

        existing_chat = (
            Chat.objects.filter(chat_type=Chat.ChatType.PERSONAL)
            .filter(participants__user=request.user, participants__is_active=True)
            .filter(participants__user=target_user, participants__is_active=True)
            .distinct()
            .order_by("-last_message_at")
            .first()
        )
        if existing_chat:
            payload = ChatInfoSerializer(existing_chat, context={"request": request}).data
            return Response({"created": False, "chat": payload})

        chat = Chat.objects.create(
            chat_type=Chat.ChatType.PERSONAL,
            title="",
            created_by=request.user,
        )
        ChatParticipant.objects.bulk_create(
            [
                ChatParticipant(chat=chat, user=request.user, is_admin=False, is_active=True),
                ChatParticipant(chat=chat, user=target_user, is_admin=False, is_active=True),
            ],
            ignore_conflicts=True,
        )
        emit_added_to_group(chat, [target_user.id], added_by_id=request.user.id)
        payload = ChatInfoSerializer(chat, context={"request": request}).data
        return Response({"created": True, "chat": payload}, status=201)


class ChatListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={200: ChatListItemSerializer(many=True)},
    )
    def get(self, request):
        sync_user_default_role_chat(request.user, emit_events=True)
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

    @extend_schema(
        tags=["chat"],
        responses={200: MessageSerializer(many=True), 404: ErrorDetailSerializer},
    )
    def get(self, request, chat_id: str):
        chat, participant = resolve_chat_and_participant(request.user, chat_id)
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
    def post(self, request, chat_id: str):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)

        serializer = MessageCreateSerializer(
            data=request.data, context={"request": request, "chat": chat}
        )
        serializer.is_valid(raise_exception=True)
        msg = serializer.save()
        emit_new_message(msg)
        return Response(MessageSerializer(msg).data, status=201)


class ChatInfoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={200: ChatInfoSerializer, 404: ErrorDetailSerializer},
    )
    def get(self, request, chat_id: str):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)
        return Response(ChatInfoSerializer(chat, context={"request": request}).data)


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
    def post(self, request, chat_id: str):
        _chat, participant = resolve_chat_and_participant(request.user, chat_id)
        if not participant:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)

        serializer = MarkReadSerializer(
            data=request.data or {},
            context={"chat": participant.chat, "participant": participant},
        )
        serializer.is_valid(raise_exception=True)
        payload = serializer.save()
        emit_message_read(participant.chat_id, request.user.id, payload.get("last_read_at"))
        return Response(payload)
