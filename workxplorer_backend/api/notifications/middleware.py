import jwt
from django.conf import settings
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model


User = get_user_model()


@database_sync_to_async
def get_user(user_id):
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


class JwtAuthMiddleware(BaseMiddleware):
    """
    Custom WebSocket middleware to authenticate users using JWT tokens.
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        token = None

        if "token=" in query_string:
            token = query_string.split("token=")[-1]

        scope["user"] = None

        if token:
            try:
                payload = jwt.decode(
                    token,
                    settings.SECRET_KEY,
                    algorithms=["HS256"],
                )
                user = await get_user(payload.get("user_id"))
                scope["user"] = user
            except Exception:
                scope["user"] = None

        return await super().__call__(scope, receive, send)
