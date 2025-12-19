from twilio.rest import Client
from django.conf import settings
import logging

log = logging.getLogger(__name__)

client = Client(
    settings.TWILIO_ACCOUNT_SID,
    settings.TWILIO_AUTH_TOKEN,
)


def send_sms_otp(e164_phone: str) -> bool:
    try:
        verification = client.verify.v2.services(
            settings.TWILIO_VERIFY_SERVICE_SID
        ).verifications.create(
            to=e164_phone,
            channel="sms",
        )
        return verification.status == "pending"
    except Exception as e:
        log.exception(f"Twilio SMS OTP send failed: {e}")
        return False


def check_sms_otp(e164_phone: str, code: str) -> bool:
    try:
        result = client.verify.v2.services(
            settings.TWILIO_VERIFY_SERVICE_SID
        ).verification_checks.create(
            to=e164_phone,
            code=code,
        )
        return result.status == "approved"
    except Exception as e:
        log.exception(f"Twilio SMS OTP check failed: {e}")
        return False
