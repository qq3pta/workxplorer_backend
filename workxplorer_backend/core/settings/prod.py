from .base import *  # noqa: F403


# helpers
def env_bool(name: str, default: bool = False) -> bool:
    v = getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _csv(name: str) -> list[str]:
    return [x.strip() for x in getenv(name, "").split(",") if x.strip()]

# --- базовое ---
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = _csv("ALLOWED_HOSTS") or ["yourdomain.com"]

# CORS / CSRF
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", False)
CORS_ALLOWED_ORIGINS = _csv("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = _csv("CSRF_TRUSTED_ORIGINS")

# --- безопасность за обратным прокси (nginx / LB) ---
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_HSTS_SECONDS = int(getenv("SECURE_HSTS_SECONDS", "31536000"))  # 1 год
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", True)
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- доступ к Swagger/Schema ---
OPEN_API_PUBLIC = env_bool("OPEN_API_PUBLIC", False)
SPECTACULAR_SETTINGS.update({  # noqa: F405
    "SERVE_PERMISSIONS": (
        ["rest_framework.permissions.AllowAny"]
        if OPEN_API_PUBLIC
        else ["rest_framework.permissions.IsAdminUser"]
    ),
})

# --- логирование в stdout/stderr (для контейнеров) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}