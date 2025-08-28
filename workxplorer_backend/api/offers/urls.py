from django.urls import path
from .views import (
    CreateOfferView,
    MyOffersView,
    IncomingOffersView,
    OfferDetailView,
    OfferAcceptView,
    OfferRejectView,
)

app_name = "offers"

urlpatterns = [
    path("create/", CreateOfferView.as_view(), name="create"),
    path("mine/", MyOffersView.as_view(), name="mine"),
    path("incoming/", IncomingOffersView.as_view(), name="incoming"),
    path("<int:pk>/", OfferDetailView.as_view(), name="detail"),
    path("<int:pk>/accept/", OfferAcceptView.as_view(), name="accept"),
    path("<int:pk>/reject/", OfferRejectView.as_view(), name="reject"),
]