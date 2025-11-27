import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

django.setup()


def get_websocket_urlpatterns():
    from api.notifications.routing import websocket_urlpatterns

    return websocket_urlpatterns


application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack(URLRouter(get_websocket_urlpatterns())),
    }
)
