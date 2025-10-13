import logging, requests
from django.conf import settings

log = logging.getLogger(__name__)

def send_whatsapp_otp(e164_phone: str, code: str) -> bool:
    if settings.DEV_FAKE_WHATSAPP:
        log.warning(f"[DEV_FAKE_WHATSAPP] OTP to {e164_phone}: {code}")
        return True

    if not (settings.WHATSAPP_PHONE_ID and settings.WHATSAPP_TOKEN and settings.WHATSAPP_TEMPLATE):
        log.error("WhatsApp config missing")
        return False

    url = f"https://graph.facebook.com/v20.0/{settings.WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": e164_phone.replace("+",""),
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_TEMPLATE,
            "language": {"code": settings.WHATSAPP_LANG},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": code}]}],
        },
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if 200 <= r.status_code < 300:
            return True
        log.error("WhatsApp send failed: %s %s", r.status_code, r.text)
        return False
    except Exception:
        log.exception("WhatsApp send exception")
        return False