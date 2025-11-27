import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from urllib.parse import parse_qs


class JwtAuthMiddleware:
    """
    Custom JWT auth for WebSockets.
    """

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, scope):
        User = get_user_model()

        query = parse_qs(scope["query_string"].decode())
        token = query.get("token", [None])[0]

        scope["user"] = None

        if token:
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
                user_id = payload.get("user_id")
                scope["user"] = User.objects.get(id=user_id)
            except Exception:
                scope["user"] = None

        return self.inner(scope)
