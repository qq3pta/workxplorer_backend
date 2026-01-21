from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import OrdersViewSet, SharedOrderView

app_name = "orders"

router = DefaultRouter()
router.register(r"", OrdersViewSet, basename="orders")

urlpatterns = [
    path(
        "orders/shared/<uuid:share_token>/",
        SharedOrderView.as_view(),
        name="order-shared",
    ),
]

urlpatterns += router.urls
