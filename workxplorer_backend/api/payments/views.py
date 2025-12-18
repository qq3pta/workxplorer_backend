from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Payment
from .serializers import PaymentCreateSerializer, PaymentSerializer


class PaymentCreateView(generics.CreateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentCreateSerializer
    permission_classes = [IsAuthenticated]


class ConfirmByCustomerView(generics.UpdateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    def patch(self, request, pk):
        payment = self.get_object()

        if request.user != payment.order.customer:
            return Response(
                {"detail": "Только заказчик может подтвердить оплату."},
                status=status.HTTP_403_FORBIDDEN,
            )

        payment.confirmed_by_customer = True
        payment.update_status()
        payment.order.update_payment_status()

        return Response(PaymentSerializer(payment).data)


class ConfirmByCarrierView(generics.UpdateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    def patch(self, request, pk):
        payment = self.get_object()

        if request.user != payment.order.carrier:
            return Response(
                {"detail": "Только перевозчик может подтвердить получение оплаты."},
                status=status.HTTP_403_FORBIDDEN,
            )

        payment.confirmed_by_carrier = True
        payment.update_status()
        payment.order.update_payment_status()

        return Response(PaymentSerializer(payment).data)


class ConfirmByLogisticView(generics.UpdateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    def patch(self, request, pk):
        payment = self.get_object()
        order = payment.order
        user = request.user

        # логист по заказу или логист-создатель
        if user not in (order.logistic, order.created_by):
            return Response(
                {"detail": "Только логист может подтвердить платёж."},
                status=status.HTTP_403_FORBIDDEN,
            )

        payment.confirmed_by_logistic = True
        payment.update_status()
        payment.order.update_payment_status()

        return Response(PaymentSerializer(payment).data)


class PaymentDetailView(generics.RetrieveAPIView):
    queryset = Payment.objects.select_related("order")
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        payment = super().get_object()
        order = payment.order
        user = self.request.user

        if user not in (
            order.customer,
            order.carrier,
            order.logistic,
            order.created_by,
        ):
            raise PermissionDenied("У вас нет доступа к этому платежу.")

        return payment
