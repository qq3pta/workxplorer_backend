import os

import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")
django.setup()

from api.chat.routing import websocket_urlpatterns as chat_ws  # noqa: E402
from api.loads.routing import websocket_urlpatterns as loads_ws  # noqa: E402
from api.notifications.middleware import JwtAuthMiddleware  # noqa: E402
from api.notifications.routing import websocket_urlpatterns as notifications_ws  # noqa: E402

combined_urlpatterns = notifications_ws + loads_ws + chat_ws

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JwtAuthMiddleware(URLRouter(combined_urlpatterns)),
    }
)
