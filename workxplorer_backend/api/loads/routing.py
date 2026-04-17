from django.urls import re_path

from .consumers import CargoConsumer

websocket_urlpatterns = [
    re_path(r"^ws/loads/?$", CargoConsumer.as_asgi()),
]
