from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils.text import slugify

from .models import ChatParticipant
from .services import ws_chat_group, ws_user_group


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or self.user.is_anonymous:
            await self.close()
            return

        await self.accept()

        self.joined_groups = set()
        await self._group_add(ws_user_group(self.user.id))

        chat_ids = await self._user_chat_ids()
        for chat_id in chat_ids:
            await self._group_add(ws_chat_group(chat_id))

    async def disconnect(self, close_code):
        for group_name in list(getattr(self, "joined_groups", set())):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        event_type = content.get("type")

        if event_type == "ping":
            await self.send_json({"type": "pong"})
            return

        if event_type == "subscribe_chat":
            chat_id = content.get("chat_id")
            resolved_id = await self._resolve_chat_id(chat_id)
            if resolved_id is None:
                await self.send_json({"event": "error", "detail": "Чат не найден или нет доступа."})
                return
            await self._group_add(ws_chat_group(resolved_id))
            await self.send_json({"event": "subscribed", "chat_id": resolved_id})
            return

        if event_type == "unsubscribe_chat":
            chat_id = content.get("chat_id")
            resolved_id = await self._resolve_chat_id(chat_id)
            if resolved_id is None:
                return
            await self._group_discard(ws_chat_group(resolved_id))
            await self.send_json({"event": "unsubscribed", "chat_id": resolved_id})
            return

        if event_type == "typing":
            chat_id = content.get("chat_id")
            is_typing = bool(content.get("is_typing", True))
            resolved_id = await self._resolve_chat_id(chat_id)
            if resolved_id is None:
                return
            await self.channel_layer.group_send(
                ws_chat_group(resolved_id),
                {
                    "type": "chat_event",
                    "data": {
                        "event": "typing",
                        "chat_id": resolved_id,
                        "user_id": self.user.id,
                        "is_typing": is_typing,
                    },
                },
            )

    async def chat_event(self, event):
        await self.send_json(event["data"])

    async def _group_add(self, group_name: str):
        if group_name in self.joined_groups:
            return
        await self.channel_layer.group_add(group_name, self.channel_name)
        self.joined_groups.add(group_name)

    async def _group_discard(self, group_name: str):
        if group_name not in self.joined_groups:
            return
        await self.channel_layer.group_discard(group_name, self.channel_name)
        self.joined_groups.discard(group_name)

    @sync_to_async
    def _user_chat_ids(self) -> list[int]:
        return list(
            ChatParticipant.objects.filter(user=self.user, is_active=True).values_list(
                "chat_id", flat=True
            )
        )

    @sync_to_async
    def _resolve_chat_id(self, chat_identifier) -> int | None:
        if chat_identifier is None:
            return None

        chat_id_str = str(chat_identifier).strip()
        qs = ChatParticipant.objects.select_related("chat").filter(user=self.user, is_active=True)

        if chat_id_str.isdigit():
            participant = qs.filter(chat_id=int(chat_id_str)).first()
            return participant.chat_id if participant else None

        target_slug = slugify(chat_id_str)
        for participant in qs:
            if slugify(participant.chat.title or "") == target_slug:
                return participant.chat_id

        return None
