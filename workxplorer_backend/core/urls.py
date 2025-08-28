from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),

    # OpenAPI/Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),

    # API
    path("api/auth/", include("api.accounts.urls")),
    path("api/loads/", include("api.loads.urls")),
    path("api/search/", include("api.search.urls")),
    path("api/offers/", include("api.offers.urls")),
]