from django.utils import timezone
from datetime import timedelta


class LastSeenMiddleware:
    """
    Обновляет last_seen, но не чаще чем раз в 60 секунд
    (чтобы не грузить БД)
    """

    UPDATE_INTERVAL = timedelta(seconds=60)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if user and user.is_authenticated:
            now = timezone.now()

            if not user.last_seen or (now - user.last_seen) > self.UPDATE_INTERVAL:
                user.last_seen = now
                user.save(update_fields=["last_seen"])

        return self.get_response(request)
