import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

# 1. Настройка Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")
django.setup()

# 2. Импорты роутинга из ВСЕХ приложений
from api.notifications.middleware import JwtAuthMiddleware
from api.notifications.routing import websocket_urlpatterns as notifications_ws
from api.loads.routing import websocket_urlpatterns as loads_ws  # Тот самый файл для карго

# 3. Объединяем списки путей в один
combined_urlpatterns = notifications_ws + loads_ws

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JwtAuthMiddleware(
            URLRouter(combined_urlpatterns)  # Используем объединенный список
        ),
    }
)
