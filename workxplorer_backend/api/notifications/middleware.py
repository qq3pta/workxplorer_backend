import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async


@database_sync_to_async
def get_user_from_token(token):
    User = get_user_model()

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


class JwtAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query = scope.get("query_string", b"").decode()

        token = None
        if "token=" in query:
            token = query.split("token=")[-1]

        if token:
            user = await get_user_from_token(token)
        else:
            user = None

        scope["user"] = user

        return await super().__call__(scope, receive, send)
