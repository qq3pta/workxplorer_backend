from django.core.mail import send_mail

def send_code_email(to_email: str, code: str, purpose: str):
    subject = "Код подтверждения" if purpose == "verify" else "Сброс пароля"
    body = f"Ваш код: {code}\nСрок действия — 15 минут."
    send_mail(subject, body, None, [to_email])