from django.utils import timezone


class LastSeenMiddleware:
    """
    Обновляет last_seen при любом HTTP запросе пользователя
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if user and user.is_authenticated:
            user.last_seen = timezone.now()
            user.save(update_fields=["last_seen"])

        return self.get_response(request)
