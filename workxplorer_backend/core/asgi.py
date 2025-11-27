import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

# --------------------------------------------------------------
# Настройка Django ДО любых импортов из Django
# --------------------------------------------------------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")
django.setup()

# --------------------------------------------------------------
# Теперь можно импортировать зависимости Django
# --------------------------------------------------------------
from api.notifications.middleware import JwtAuthMiddleware  # noqa: E402
from api.notifications.routing import websocket_urlpatterns  # noqa: E402

# --------------------------------------------------------------
# ASGI-приложение
# --------------------------------------------------------------
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JwtAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
