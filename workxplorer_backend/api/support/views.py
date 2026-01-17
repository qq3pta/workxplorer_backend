from django.conf import settings
from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema

from .models import SupportTicket, ConsultationRequest
from .serializers import SupportTicketCreateSerializer, ConsultationRequestSerializer


@extend_schema(
    request=SupportTicketCreateSerializer,
    responses={201: None},
)
class SupportCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SupportTicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket = SupportTicket.objects.create(
            user=request.user,
            message=serializer.validated_data["message"],
        )

        send_mail(
            subject=f"[Support #{ticket.id}] Новое обращение",
            message=f"""Пользователь: {request.user.email or request.user.username}
ID: {request.user.id}

Сообщение:
{ticket.message}
""",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=["kad.noreply1@gmail.com"],
        )

        return Response(
            {"detail": "Сообщение отправлено"},
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    request=ConsultationRequestSerializer,
    responses={
        201: {"type": "object", "properties": {"detail": {"type": "string"}}},
        400: {
            "type": "object",
            "properties": {"email": {"type": "array", "items": {"type": "string"}}},
        },
    },
)
class ConsultationRequestView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = ConsultationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        consultation, created = ConsultationRequest.objects.get_or_create(
            email=serializer.validated_data["email"]
        )

        if created:
            send_mail(
                subject="Новая заявка на консультацию",
                message=f"Email: {consultation.email}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=["kad.noreply1@gmail.com"],
            )

        return Response(
            {"detail": "Заявка принята"},
            status=status.HTTP_201_CREATED,
        )
