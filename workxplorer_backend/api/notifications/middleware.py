import logging
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)
User = get_user_model()


class JwtAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        scope["user"] = AnonymousUser()

        try:
            token = self._get_token_from_scope(scope)
            if not token:
                return await self.inner(scope, receive, send)

            access = AccessToken(token)

            # Явная проверка типа токена
            if access.get("token_type") != "access":
                raise TokenError("Not an access token")

            user_id = access.get("user_id")
            if not user_id:
                raise TokenError("user_id missing in token")

            user = await self._get_user(user_id)
            if user and not user.is_anonymous:
                scope["user"] = user

        except TokenError as e:
            logger.info("WS JWT rejected: %s", e)

        except Exception as e:
            logger.exception("WS auth unexpected error: %s", e)

        return await self.inner(scope, receive, send)

    @staticmethod
    def _get_token_from_scope(scope) -> str | None:
        query_string = scope.get("query_string", b"").decode()
        query = parse_qs(query_string)
        return query.get("token", [None])[0]

    @staticmethod
    async def _get_user(user_id):
        try:
            return await User.objects.aget(id=user_id)
        except User.DoesNotExist:
            return AnonymousUser()
