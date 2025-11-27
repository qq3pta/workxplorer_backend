import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

from api.notifications.middleware import JwtAuthMiddleware
from api.notifications.routing import websocket_urlpatterns


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JwtAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
