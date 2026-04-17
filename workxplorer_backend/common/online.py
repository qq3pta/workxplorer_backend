from datetime import timedelta

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()
UPDATE_INTERVAL = timedelta(seconds=60)


@database_sync_to_async
def touch_last_seen(user_id: int):
    now = timezone.now()

    u = User.objects.only("id", "last_seen").get(id=user_id)

    if (u.last_seen is None) or ((now - u.last_seen) > UPDATE_INTERVAL):
        User.objects.filter(id=user_id).update(last_seen=now)
