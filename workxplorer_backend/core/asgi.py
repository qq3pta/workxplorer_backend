import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application

# 1. Настраиваем Django ещё до любых импортов
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")

# 2. Запуск Django
django.setup()

# 3. Только теперь можно импортировать всё что связано с Django
from api.notifications.middleware import JwtAuthMiddleware
from api.notifications.routing import websocket_urlpatterns

# 4. HTTP → обычное django ASGI-приложение
django_asgi_app = get_asgi_application()

# 5. Финальная конфигурация channels
application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JwtAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
