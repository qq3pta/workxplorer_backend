import os
import django

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

from api.notifications.middleware import JwtAuthMiddleware
from api.notifications.routing import websocket_urlpatterns

# --- SETTINGS MUST BE SET BEFORE DJANGO.SETUP ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")

# --- INIT DJANGO ---
django.setup()

# --- ASGI APPLICATION ---
application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": JwtAuthMiddleware(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
    }
)
