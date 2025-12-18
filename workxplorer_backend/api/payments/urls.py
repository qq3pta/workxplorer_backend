from django.urls import path

from .views import (
    PaymentDetailView,
    ConfirmByCarrierView,
    ConfirmByCustomerView,
    ConfirmByLogisticView,
)

urlpatterns = [
    path("<int:pk>/", PaymentDetailView.as_view()),
    path("<int:pk>/confirm/customer/", ConfirmByCustomerView.as_view()),
    path("<int:pk>/confirm/carrier/", ConfirmByCarrierView.as_view()),
    path("<int:pk>/confirm/logistic/", ConfirmByLogisticView.as_view()),
]
