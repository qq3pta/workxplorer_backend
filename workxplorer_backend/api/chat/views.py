from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Chat, ChatParticipant, Message
from .serializers import (
    ChatInfoSerializer,
    ChatInvitationItemSerializer,
    ChatListItemSerializer,
    ChatMuteSerializer,
    ChatSummarySerializer,
    GroupAddParticipantsSerializer,
    GroupCreateSerializer,
    GroupInviteDecisionSerializer,
    InviteLinkRequestSerializer,
    InviteLinkResponseSerializer,
    JoinByLinkSerializer,
    MarkReadSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    OpenPersonalChatSerializer,
    UserSearchResultSerializer,
    build_user_display_name,
)
from .services import (
    emit_added_to_group,
    emit_chat_removed,
    emit_group_deleted,
    emit_group_invite_request,
    emit_member_joined,
    emit_member_kicked,
    emit_member_left,
    emit_message_deleted,
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


def resolve_chat_participant_any_status(user, chat_identifier: str):
    chat_id_str = str(chat_identifier).strip()

    if chat_id_str.isdigit():
        try:
            participant = ChatParticipant.objects.select_related("chat").get(
                chat_id=int(chat_id_str), user=user
            )
            return participant.chat, participant
        except ChatParticipant.DoesNotExist:
            return None, None

    target_slug = slugify(chat_id_str)
    participants = ChatParticipant.objects.select_related("chat").filter(user=user)
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


class OrderChatView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={200: ChatInfoSerializer, 403: ErrorDetailSerializer, 404: ErrorDetailSerializer},
    )
    def get(self, request, order_id: int):
        from api.orders.models import Order

        order = (
            Order.objects.select_related("chat")
            .filter(id=order_id)
            .only(
                "id",
                "chat_id",
                "customer_id",
                "carrier_id",
                "logistic_id",
                "created_by_id",
                "invited_carrier_id",
            )
            .first()
        )
        if not order:
            return Response({"detail": "Заказ не найден."}, status=404)

        allowed_user_ids = {
            user_id
            for user_id in (
                order.customer_id,
                order.carrier_id,
                order.logistic_id,
                order.created_by_id,
                order.invited_carrier_id,
            )
            if user_id
        }
        if request.user.id not in allowed_user_ids:
            return Response({"detail": "Нет доступа к чату заказа."}, status=403)

        if not order.chat_id:
            return Response({"detail": "Чат заказа ещё не создан."}, status=404)

        participant = (
            ChatParticipant.objects.filter(
                chat_id=order.chat_id,
                user=request.user,
                is_active=True,
            )
            .select_related("chat")
            .first()
        )
        if not participant:
            return Response({"detail": "Нет доступа к чату заказа."}, status=403)

        chat = participant.chat
        chat._viewer_participant = participant
        return Response(ChatInfoSerializer(chat, context={"request": request}).data)


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
        participant_ids = serializer.validated_data.get("participant_ids", [])
        users_qs = User.objects.filter(id__in=participant_ids).exclude(id=request.user.id)

        invited_user_ids = []
        for user in users_qs:
            participant, created = ChatParticipant.objects.get_or_create(
                chat=chat,
                user=user,
                defaults={
                    "is_active": False,
                    "is_admin": False,
                    "invited_by": request.user,
                    "invited_at": timezone.now(),
                },
            )
            if created:
                invited_user_ids.append(user.id)
                continue

            participant.is_active = False
            participant.is_admin = False
            participant.invited_by = request.user
            participant.invited_at = timezone.now()
            participant.save(update_fields=["is_active", "is_admin", "invited_by", "invited_at"])
            invited_user_ids.append(user.id)

        if invited_user_ids:
            emit_group_invite_request(
                chat,
                invited_user_ids,
                invited_by_id=request.user.id,
                invited_by_name=request.user.get_full_name() or request.user.username or "",
            )

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
                    "invited_user_ids": serializers.ListField(child=serializers.IntegerField()),
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

        invited_user_ids: list[int] = []
        for user in users_qs:
            participant, created = ChatParticipant.objects.get_or_create(
                chat=chat,
                user=user,
                defaults={
                    "is_active": False,
                    "is_admin": False,
                    "invited_by": request.user,
                    "invited_at": timezone.now(),
                },
            )
            if participant.is_active:
                continue

            participant.is_active = False
            participant.is_admin = False
            participant.invited_by = request.user
            participant.invited_at = timezone.now()
            participant.save(update_fields=["is_active", "is_admin", "invited_by", "invited_at"])
            invited_user_ids.append(user.id)

        if invited_user_ids:
            emit_group_invite_request(
                chat,
                invited_user_ids,
                invited_by_id=request.user.id,
                invited_by_name=request.user.get_full_name() or request.user.username or "",
            )

        return Response(
            {"chat": ChatSummarySerializer(chat).data, "invited_user_ids": invited_user_ids}
        )


class GroupKickMemberView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={
            204: None,
            400: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def delete(self, request, chat_id: str, user_id: int):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден."}, status=404)
        if chat.chat_type != Chat.ChatType.GROUP:
            return Response({"detail": "Кик доступен только в групповом чате."}, status=400)
        if not user_can_manage_group(chat, request.user.id):
            return Response({"detail": "Недостаточно прав для управления участниками."}, status=403)
        if user_id == request.user.id:
            return Response({"detail": "Нельзя кикнуть самого себя."}, status=400)
        if chat.created_by_id == user_id:
            return Response({"detail": "Нельзя кикнуть владельца группы."}, status=400)

        target = ChatParticipant.objects.filter(chat=chat, user_id=user_id, is_active=True).first()
        if not target:
            return Response({"detail": "Участник не найден."}, status=404)

        target.is_active = False
        target.is_admin = False
        target.invited_by = None
        target.invited_at = None
        target.save(update_fields=["is_active", "is_admin", "invited_by", "invited_at"])

        emit_member_kicked(chat.id, user_id=user_id, kicked_by_id=request.user.id)
        emit_chat_removed(user_id, chat.id, reason="kicked_from_group")
        return Response(status=204)


class GroupInviteDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=GroupInviteDecisionSerializer,
        responses={
            200: ChatSummarySerializer,
            204: None,
            400: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, chat_id: str):
        chat, participant = resolve_chat_participant_any_status(request.user, chat_id)
        if not chat or not participant:
            return Response({"detail": "Приглашение не найдено."}, status=404)
        if chat.chat_type != Chat.ChatType.GROUP:
            return Response({"detail": "Приглашение доступно только для группы."}, status=400)
        if participant.is_active or not participant.invited_by_id:
            return Response({"detail": "Приглашение не найдено."}, status=404)

        serializer = GroupInviteDecisionSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]

        if action == "accept":
            participant.is_active = True
            participant.invited_by = None
            participant.invited_at = None
            participant.save(update_fields=["is_active", "invited_by", "invited_at"])
            emit_added_to_group(chat, [request.user.id], added_by_id=None)
            emit_member_joined(chat, request.user.id)
            return Response(ChatSummarySerializer(chat).data, status=200)

        participant.delete()
        return Response(status=204)


class GroupInviteAcceptDirectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={200: ChatSummarySerializer, 404: ErrorDetailSerializer},
    )
    def post(self, request, chat_id: str):
        chat, participant = resolve_chat_participant_any_status(request.user, chat_id)
        if not chat or not participant or participant.is_active or not participant.invited_by_id:
            return Response({"detail": "Приглашение не найдено."}, status=404)

        participant.is_active = True
        participant.invited_by = None
        participant.invited_at = None
        participant.save(update_fields=["is_active", "invited_by", "invited_at"])

        emit_added_to_group(chat, [request.user.id], added_by_id=None)
        emit_member_joined(chat, request.user.id)
        return Response(ChatSummarySerializer(chat).data, status=200)


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
        participant.invited_by = None
        participant.invited_at = None
        participant.save(update_fields=["is_active", "is_admin", "invited_by", "invited_at"])

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
        responses={
            200: inline_serializer(
                "ChatFeedResponseItem",
                {
                    "id": serializers.IntegerField(),
                    "chat_type": serializers.CharField(),
                    "title": serializers.CharField(required=False, allow_blank=True),
                    "display_title": serializers.CharField(required=False, allow_blank=True),
                    "participants_count": serializers.IntegerField(required=False),
                    "unread_count": serializers.IntegerField(required=False),
                    "last_message": serializers.JSONField(required=False, allow_null=True),
                    "last_message_at": serializers.DateTimeField(required=False, allow_null=True),
                    "created_at": serializers.DateTimeField(required=False),
                    "invitation_group_id": serializers.IntegerField(required=False),
                    "invitation_group_title": serializers.CharField(
                        required=False, allow_blank=True
                    ),
                    "invitation_participants_count": serializers.IntegerField(required=False),
                    "invited_by": serializers.JSONField(required=False, allow_null=True),
                    "invited_at": serializers.DateTimeField(required=False, allow_null=True),
                },
                many=True,
            )
        },
    )
    def get(self, request):
        sync_user_default_role_chat(request.user, emit_events=True)
        active_participants = (
            ChatParticipant.objects.filter(user=request.user, is_active=True)
            .select_related("chat")
            .order_by("-chat__last_message_at")
        )
        chats = []
        for participant in active_participants:
            chat = participant.chat
            chat._viewer_participant = participant
            chats.append(chat)
        feed = ChatListItemSerializer(chats, many=True, context={"request": request}).data

        pending_participants = (
            ChatParticipant.objects.filter(
                user=request.user,
                is_active=False,
                invited_by__isnull=False,
                chat__chat_type=Chat.ChatType.GROUP,
            )
            .select_related("chat", "invited_by")
            .order_by("-invited_at", "-chat__updated_at")
        )
        for participant in pending_participants:
            invitation_item = ChatInvitationItemSerializer(
                {
                    "id": participant.chat_id,
                    "chat_type": "invitation",
                    "title": participant.chat.title,
                    "display_title": participant.chat.title,
                    "participants_count": participant.chat.participants.filter(
                        is_active=True
                    ).count(),
                    "unread_count": 0,
                    "last_message": None,
                    "last_message_at": None,
                    "created_at": participant.chat.created_at,
                    "invitation_group_id": participant.chat_id,
                    "invitation_group_title": participant.chat.title,
                    "invitation_participants_count": participant.chat.participants.filter(
                        is_active=True
                    ).count(),
                    "invited_by": participant.invited_by,
                    "invited_at": participant.invited_at,
                },
                context={"request": request},
            ).data
            feed.append(invitation_item)

        return Response(feed)


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
        return Response(MessageSerializer(messages, many=True, context={"request": request}).data)

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
        return Response(MessageSerializer(msg, context={"request": request}).data, status=201)


class ChatExportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={
            (200, "text/plain"): OpenApiTypes.BINARY,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, chat_id: str):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)

        messages = (
            chat.messages.select_related("sender")
            .order_by("created_at")
            .only(
                "sender_id",
                "sender__first_name",
                "sender__last_name",
                "sender__username",
                "text",
                "created_at",
            )
        )

        lines = [
            f"Chat #{chat.id}",
            f"Exported at: {timezone.localtime(timezone.now()).isoformat()}",
            "",
        ]

        for msg in messages:
            text = (msg.text or "").strip()
            if not text:
                # Skip attachment-only messages by design: export is text history only.
                continue
            sender_name = (
                build_user_display_name(msg.sender) if msg.sender else "Удаленный пользователь"
            )
            created_at = timezone.localtime(msg.created_at).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{created_at}] {sender_name}: {text}")

        if len(lines) == 3:
            lines.append("В этом чате нет текстовых сообщений для экспорта.")

        content = "\n".join(lines) + "\n"
        filename = f"chat_{chat.id}_history.txt"

        response = HttpResponse(content, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ChatMessageDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={204: None, 403: ErrorDetailSerializer, 404: ErrorDetailSerializer},
    )
    def delete(self, request, chat_id: str, message_id: int):
        chat, _participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)
        if chat.chat_type != Chat.ChatType.GROUP:
            return Response(
                {"detail": "Удаление сообщений доступно только в групповых чатах."}, status=403
            )
        if not user_can_manage_group(chat, request.user.id):
            return Response({"detail": "Недостаточно прав для удаления сообщения."}, status=403)

        message = Message.objects.filter(chat=chat, id=message_id).first()
        if not message:
            return Response({"detail": "Сообщение не найдено."}, status=404)

        message.delete()
        emit_message_deleted(chat.id, message_id=message_id, deleted_by_id=request.user.id)
        return Response(status=204)


class ChatInfoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        responses={200: ChatInfoSerializer, 404: ErrorDetailSerializer},
    )
    def get(self, request, chat_id: str):
        chat, participant = resolve_chat_and_participant(request.user, chat_id)
        if not chat:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)
        chat._viewer_participant = participant
        return Response(ChatInfoSerializer(chat, context={"request": request}).data)


class ChatMuteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["chat"],
        request=ChatMuteSerializer,
        responses={
            200: inline_serializer(
                "ChatMuteResponse",
                {"chat_id": serializers.IntegerField(), "is_muted": serializers.BooleanField()},
            ),
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, chat_id: str):
        _chat, participant = resolve_chat_and_participant(request.user, chat_id)
        if not participant:
            return Response({"detail": "Чат не найден или нет доступа."}, status=404)

        serializer = ChatMuteSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        participant.is_muted = serializer.validated_data["is_muted"]
        participant.save(update_fields=["is_muted"])
        return Response({"chat_id": participant.chat_id, "is_muted": participant.is_muted})


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
