import jwt
from django.conf import settings
from channels.middleware import BaseMiddleware


class JwtAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        # Отложенные импорты, чтобы Django был уже настроен
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import AnonymousUser

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", None)

        if auth_header:
            try:
                token = auth_header.decode().split(" ")[1]
                payload = jwt.decode(
                    token,
                    settings.SECRET_KEY,
                    algorithms=["HS256"],
                )
                user = await get_user_model().objects.aget(id=payload["user_id"])
                scope["user"] = user
            except Exception:
                scope["user"] = AnonymousUser()
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
