from django.core.mail import send_mail
from django.conf import settings


def send_code_email(to_email: str, code: str, purpose: str):
    """
    Отправка кода подтверждения или сброса пароля.
    """
    subject = "Код подтверждения" if purpose == "verify" else "Сброс пароля"
    body = f"Ваш код: {code}\nСрок действия — 15 минут."
    send_mail(
        subject,
        body,
        getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"),
        [to_email],
        fail_silently=True,
    )


def send_simple_email(to_email: str, subject: str, message: str):
    """
    Универсальная функция для системных уведомлений (о сделках, статусах и т.д.).
    """
    send_mail(
        subject,
        message,
        getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"),
        [to_email],
        fail_silently=True,
    )