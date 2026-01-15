from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives


def send_code_email(to_email: str, code: str, purpose: str):
    """
    Отправка кода подтверждения или сброса пароля.
    """
    subject = "Код подтверждения" if purpose == "verify" else "Сброс пароля"
    text_content = f"Ваш код: {code}\nСрок действия — 15 минут."
    html_content = f"""
    <html>
      <body>
        <p>Ваш код: <b>{code}</b></p>
        <p>Срок действия — 15 минут.</p>
      </body>
    </html>
    """

    msg = EmailMultiAlternatives(
        subject,
        text_content,
        getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"),
        [to_email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send(fail_silently=False)


def send_simple_email(to_email: str, subject: str, message: str):
    """
    Универсальная функция для системных уведомлений (о сделках, статусах и т.д.).
    """
    send_mail(
        subject,
        message,
        getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"),
        [to_email],
        fail_silently=False,
    )
