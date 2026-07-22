import logging

import requests
from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

log = logging.getLogger(__name__)

ESKIZ_TOKEN_CACHE_KEY = "eskiz_sms_token"
ESKIZ_TOKEN_CACHE_SECONDS = 60 * 60 * 24 * 25


def _sms_validation_error(message: str) -> ValidationError:
    return ValidationError({"detail": message})


def _eskiz_base_url() -> str:
    return str(getattr(settings, "ESKIZ_BASE_URL", "https://notify.eskiz.uz")).rstrip("/")


def _eskiz_credentials() -> tuple[str, str]:
    email = getattr(settings, "ESKIZ_EMAIL", "")
    password = getattr(settings, "ESKIZ_PASSWORD", "")
    if not email or not password:
        raise _sms_validation_error("SMS gateway is not configured.")
    return email, password


def _get_eskiz_token(force_refresh: bool = False) -> str:
    if not force_refresh:
        cached_token = cache.get(ESKIZ_TOKEN_CACHE_KEY)
        if cached_token:
            return cached_token

    email, password = _eskiz_credentials()
    try:
        response = requests.post(
            f"{_eskiz_base_url()}/api/auth/login",
            data={"email": email, "password": password},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.exception("Eskiz auth failed: %s", exc)
        raise _sms_validation_error("Не удалось подключиться к SMS шлюзу. Попробуйте позже.") from None

    token = (payload.get("data") or {}).get("token")
    if not token:
        log.error("Eskiz auth response does not contain token: %s", payload)
        raise _sms_validation_error("SMS шлюз не вернул токен авторизации.")

    cache.set(ESKIZ_TOKEN_CACHE_KEY, token, ESKIZ_TOKEN_CACHE_SECONDS)
    return token


def _normalize_eskiz_phone(e164_phone: str) -> str:
    return "".join(ch for ch in str(e164_phone or "") if ch.isdigit())


def _build_otp_message(code: str, purpose: str) -> str:
    if purpose == "reset":
        return f"Восстановление пароля для сайта KAD-ONE: {code}"
    return f"Код подтверждения для регистрации на сайте KAD-ONE: {code}"


def send_sms_otp(e164_phone: str, code: str, purpose: str = "verify") -> None:
    message = _build_otp_message(code, purpose)
    send_sms(e164_phone=e164_phone, message=message)


def _eskiz_error_message(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    return payload.get("message") or ""


def send_sms(e164_phone: str, message: str) -> None:
    phone = _normalize_eskiz_phone(e164_phone)
    sender = getattr(settings, "ESKIZ_FROM", "")
    if not sender:
        raise _sms_validation_error("SMS sender is not configured.")

    data = {
        "mobile_phone": phone,
        "message": message,
        "from": sender,
    }

    for attempt in range(2):
        token = _get_eskiz_token(force_refresh=attempt == 1)
        try:
            response = requests.post(
                f"{_eskiz_base_url()}/api/message/sms/send",
                data=data,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if response.status_code == 401 and attempt == 0:
                cache.delete(ESKIZ_TOKEN_CACHE_KEY)
                continue
            if response.status_code >= 400:
                log.error(
                    "Eskiz SMS send rejected: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                error_message = _eskiz_error_message(response)
                if error_message:
                    raise _sms_validation_error(error_message)
            response.raise_for_status()
            payload = response.json()
        except ValidationError:
            raise
        except Exception as exc:
            log.exception("Eskiz SMS send failed: %s", exc)
            raise _sms_validation_error("Не удалось отправить код. Попробуйте позже.") from None

        if payload.get("status") not in {"success", "waiting"}:
            log.error("Eskiz SMS send returned unexpected response: %s", payload)
            raise _sms_validation_error("SMS шлюз не принял сообщение.")
        return

    raise _sms_validation_error("Не удалось авторизоваться в SMS шлюзе.")
