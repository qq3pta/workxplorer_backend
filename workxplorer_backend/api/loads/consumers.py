from channels.generic.websocket import AsyncJsonWebsocketConsumer


class CargoConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]

        if not self.user or self.user.is_anonymous:
            await self.close()
            return

        await self.accept()

        await self.channel_layer.group_add(f"user_{self.user.id}", self.channel_name)
        await self.channel_layer.group_add("loads_all", self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(f"user_{self.user.id}", self.channel_name)
        await self.channel_layer.group_discard("loads_all", self.channel_name)

    async def cargo_updated(self, event):
        await self.send_json(event["data"])
