from django.conf import settings
from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema

from .models import SupportTicket
from .serializers import SupportTicketCreateSerializer


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
