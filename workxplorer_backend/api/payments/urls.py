from django.urls import path
from .views import PaymentCreateView, ConfirmByCustomerView, ConfirmByCarrierView

urlpatterns = [
    path("create/", PaymentCreateView.as_view()),
    path("<int:pk>/confirm/customer/", ConfirmByCustomerView.as_view()),
    path("<int:pk>/confirm/carrier/", ConfirmByCarrierView.as_view()),
]
