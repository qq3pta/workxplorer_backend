from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from common.ws_utils import to_ws_safe

from .models import Payment
from .serializers import PaymentCreateSerializer, PaymentSerializer


def _notify_payment(payment, request, event):
    channel_layer = get_channel_layer()

    order = payment.order
    participants = {
        order.customer_id,
        order.carrier_id,
        order.logistic_id,
        order.created_by_id,
    }

    payload = PaymentSerializer(payment, context={"request": request}).data

    for user_id in filter(None, participants):
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            to_ws_safe(
                {
                    "type": "notify",
                    "data": {
                        "event": event,
                        "payment": payload,
                    },
                }
            ),
        )


class PaymentCreateView(generics.CreateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentCreateSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        payment = serializer.save()
        payment.refresh_from_db()
        _notify_payment(payment, self.request, "payment_created")


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
        payment.refresh_from_db()

        _notify_payment(payment, self.request, "payment_updated")

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
        payment.refresh_from_db()

        _notify_payment(payment, self.request, "payment_updated")

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
        payment.refresh_from_db()

        _notify_payment(payment, self.request, "payment_updated")

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
