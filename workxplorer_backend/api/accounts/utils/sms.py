from twilio.rest import Client
from django.conf import settings
from django.core.exceptions import ValidationError
import logging

log = logging.getLogger(__name__)

client = Client(
    settings.TWILIO_ACCOUNT_SID,
    settings.TWILIO_AUTH_TOKEN,
)


def send_sms_otp(e164_phone: str) -> None:
    try:
        client.verify.v2.services(settings.TWILIO_VERIFY_SERVICE_SID).verifications.create(
            to=e164_phone,
            channel="sms",
        )
    except Exception as e:
        log.exception(f"Twilio SMS OTP send failed: {e}")
        raise ValidationError("Не удалось отправить код. Попробуйте позже.")


def check_sms_otp(e164_phone: str, code: str) -> None:
    try:
        result = client.verify.v2.services(
            settings.TWILIO_VERIFY_SERVICE_SID
        ).verification_checks.create(
            to=e164_phone,
            code=code,
        )
    except Exception as e:
        log.exception(f"Twilio SMS OTP check failed: {e}")
        raise ValidationError("Код неверный или просроченный")

    if result.status != "approved":
        raise ValidationError("Код неверный или просроченный")
