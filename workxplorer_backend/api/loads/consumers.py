from channels.generic.websocket import AsyncJsonWebsocketConsumer
from common.online import touch_last_seen


class CargoConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]

        if not self.user or self.user.is_anonymous:
            await self.close()
            return

        # пользователь стал ONLINE
        await touch_last_seen(self.user.id)

        await self.accept()

        await self.channel_layer.group_add(f"user_{self.user.id}", self.channel_name)
        await self.channel_layer.group_add("loads_all", self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(f"user_{self.user.id}", self.channel_name)
        await self.channel_layer.group_discard("loads_all", self.channel_name)

    # -------- HEARTBEAT (чтобы онлайн не пропадал) --------
    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            if self.user and not self.user.is_anonymous:
                await touch_last_seen(self.user.id)

            await self.send_json({"type": "pong"})

    async def cargo_updated(self, event):
        await self.send_json(event["data"])

    async def notify(self, event):
        await self.send_json(event["data"])
