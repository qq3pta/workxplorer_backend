from datetime import timedelta
from os import getenv
from pathlib import Path

import firebase_admin
from corsheaders.defaults import default_headers
from dotenv import load_dotenv
from firebase_admin import credentials

# Paths & env
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _csv(name: str, default: str = "") -> list[str]:
    raw = getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# Core
SECRET_KEY = getenv("DJANGO_SECRET_KEY", "dev-secret")
DEBUG = getenv("DJANGO_DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = (
    _csv("ALLOWED_HOSTS")
    or _csv("DJANGO_ALLOWED_HOSTS", "*" if DEBUG else "")
    or (["*"] if DEBUG else [])
)

# CSRF
CSRF_TRUSTED_ORIGINS = _csv("CSRF_TRUSTED_ORIGINS") or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://95.182.119.148:3000",
    "http://95.182.119.148",
]

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    # 3rd-party
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    # API
    "api.accounts",
    "api.loads",
    "api.offers",
    "api.search",
    "api.geo",
    "api.routing",
    "api.orders",
    "api.ratings",
    "api.notifications",
    "channels",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# Database
if getenv("DATABASE_URL"):
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            getenv("DATABASE_URL"),
            conn_max_age=600,
            ssl_require=False,
        )
    }
    DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": getenv("DB_NAME", "postgres"),
            "USER": getenv("DB_USER", "postgres"),
            "PASSWORD": getenv("DB_PASSWORD", "postgres"),
            "HOST": getenv("DB_HOST", "localhost"),
            "PORT": getenv("DB_PORT", "5432"),
        }
    }

# Passwords / i18n / tz
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

# Static / Media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# STORAGES
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF / Schema
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "5000/day",
        "anon": "1000/day",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Workxplorer Backend API",
    "DESCRIPTION": "API docs",
    "VERSION": "1.0.0",
    "ENUM_GENERATE_UNIQUE_NAME": False,
    "ENUM_NAME_OVERRIDES": {
        # Accounts
        "api.accounts.models.UserRole": "UserRoleEnum",
        # Loads
        "api.loads.choices.Currency": "CurrencyEnum",
        "api.loads.choices.TransportType": "TransportTypeEnum",
        "api.loads.choices.ModerationStatus": "ModerationStatusEnum",
        "api.loads.choices.ContactPref": "ContactPrefEnum",
        "api.loads.models.CargoStatus": "CargoStatusEnum",
        # Offers
        "api.offers.models.OfferStatus": "OfferStatusEnum",
        # Orders
        "api.orders.models.OrderStatus": "OrderStatusEnum",
        "api.orders.models.DocumentCategory": "DocumentCategoryEnum",
    },
    "COMPONENT_SPLIT_REQUEST": True,
    "POSTPROCESSING_HOOKS": [],
}

# JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(getenv("JWT_ACCESS_MIN", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(getenv("JWT_REFRESH_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# CORS
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _csv("CORS_ALLOWED_ORIGINS") or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://95.182.119.148:3000",
    "http://95.182.119.148",
]
CORS_ALLOW_CREDENTIALS = True
CORS_PREFLIGHT_MAX_AGE = 86400
CORS_ALLOW_HEADERS = list(default_headers) + ["authorization"]

# Auth user / Email
AUTH_USER_MODEL = "accounts.User"
EMAIL_BACKEND = getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = getenv("DEFAULT_FROM_EMAIL", "noreply@example.com")

# Upload limits
MAX_UPLOAD_MB = int(getenv("MAX_UPLOAD_MB", "20"))
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024

# Geo / Nominatim
GEO_NOMINATIM_USER_AGENT = getenv(
    "GEO_NOMINATIM_USER_AGENT",
    "workxplorer/1.0 (+contact@example.com)",
)

# Cache (Redis)
if getenv("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": getenv("REDIS_URL"),
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --- WhatsApp / Phone OTP ---
WHATSAPP_ENABLED = getenv("WHATSAPP_ENABLED", "true").lower() == "true"
WHATSAPP_PHONE_ID = getenv("WHATSAPP_PHONE_ID")
WHATSAPP_TOKEN = getenv("WHATSAPP_TOKEN")
WHATSAPP_TEMPLATE = getenv("WHATSAPP_TEMPLATE", "otp_code")
WHATSAPP_LANG = getenv("WHATSAPP_LANG", "ru")

# Параметры OTP
OTP_TTL_SECONDS = int(getenv("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = int(getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_RECENT_MINUTES = int(getenv("OTP_RECENT_MINUTES", "10"))

DEV_FAKE_WHATSAPP = getenv("DEV_FAKE_WHATSAPP", "false").lower() == "true"

FIREBASE_CREDENTIAL_FILE = BASE_DIR / "core" / "firebase.json"

try:
    if FIREBASE_CREDENTIAL_FILE.exists() and not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_CREDENTIAL_FILE)
        firebase_admin.initialize_app(cred)
except Exception as e:
    print("Firebase init error:", e)

# WebSocket / Channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379)],
        },
    },
}

EMAIL_BACKEND = getenv("EMAIL_BACKEND")
EMAIL_HOST = getenv("EMAIL_HOST")
EMAIL_PORT = int(getenv("EMAIL_PORT"))
EMAIL_USE_TLS = getenv("EMAIL_USE_TLS") == "True"
EMAIL_HOST_USER = getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = getenv("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = getenv("DEFAULT_FROM_EMAIL")
