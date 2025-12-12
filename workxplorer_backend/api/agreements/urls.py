from rest_framework.routers import DefaultRouter

from .views import AgreementViewSet

router = DefaultRouter()
router.register(r"agreements", AgreementViewSet)

urlpatterns = router.urls
