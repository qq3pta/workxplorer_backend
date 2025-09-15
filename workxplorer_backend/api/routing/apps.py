from django.apps import AppConfig

class RoutingConfig(AppConfig):
    name = "api.routing"
    label = "routing"
    verbose_name = "Routing / Маршрутизация"
    default_auto_field = "django.db.models.BigAutoField"