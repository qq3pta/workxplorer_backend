import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")

import django

django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

from api.notifications.routing import websocket_urlpatterns
from api.notifications.middleware import JwtAuthMiddleware

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": JwtAuthMiddleware(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
    }
)
