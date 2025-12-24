from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.health import health

urlpatterns = [
    path("admin/", admin.site.urls),
    # OpenAPI/Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    # API
    path("api/auth/", include("api.accounts.urls")),
    path("api/loads/", include("api.loads.urls")),
    path("api/search/", include("api.search.urls")),
    path("api/offers/", include("api.offers.urls")),
    path("api/geo/", include("api.geo.urls")),
    path("api/orders/", include("api.orders.urls")),
    path("api/ratings/", include("api.ratings.urls")),
    path("api/notifications/", include("api.notifications.urls")),
    path("api/payments/", include("api.payments.urls")),
    path("api/agreements/", include("api.agreements.urls")),
    path("api/support/", include("api.support.urls")),
    # Health
    path("health/", health),
]
