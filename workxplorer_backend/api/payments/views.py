from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Payment
from .serializers import PaymentSerializer, PaymentCreateSerializer


class PaymentCreateView(generics.CreateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentCreateSerializer
    permission_classes = [IsAuthenticated]

    class PaymentCreateView(generics.CreateAPIView):
        queryset = Payment.objects.all()
        serializer_class = PaymentCreateSerializer
        permission_classes = [IsAuthenticated]

        def perform_create(self, serializer):
            order = serializer.validated_data["order"]

            if self.request.user not in (order.customer, order.carrier, order.created_by):
                raise PermissionDenied("Вы не можете создавать платеж по этому заказу.")

            if order.carrier is None:
                raise ValidationError("Нельзя создать платеж: перевозчик не назначен.")

            payment = serializer.save()

            order.update_payment_status()

            return payment


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
