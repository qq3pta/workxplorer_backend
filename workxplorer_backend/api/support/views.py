from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import SupportTicket
from .serializers import SupportTicketCreateSerializer


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
            subject=f"Поддержка | Ticket #{ticket.id}",
            message=f"""
Пользователь: {request.user.email or request.user.username}
ID: {request.user.id}

Сообщение:
{ticket.message}
            """,
            from_email=None,
            recipient_list=["dispatch@gmail.com"],
        )

        return Response(
            {"detail": "Сообщение отправлено"},
            status=status.HTTP_201_CREATED,
        )
