from .base import *

DEBUG = False
ALLOWED_HOSTS = [h for h in ALLOWED_HOSTS if h] or ["yourdomain.com"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
