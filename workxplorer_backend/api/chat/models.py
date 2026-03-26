from django.conf import settings
from django.db import models
from django.utils import timezone


class Chat(models.Model):
    class ChatType(models.TextChoices):
        PERSONAL = "personal", "Личный"
        GROUP = "group", "Групповой"

    chat_type = models.CharField(
        max_length=16,
        choices=ChatType.choices,
        default=ChatType.PERSONAL,
    )
    title = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_chats",
    )
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-updated_at"]
        indexes = [
            models.Index(fields=["chat_type", "-last_message_at"], name="chat_type_last_msg_idx"),
        ]

    def __str__(self) -> str:
        if self.title:
            return self.title
        return f"Chat#{self.pk} ({self.chat_type})"


class ChatParticipant(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_participations",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["chat", "user"], name="uniq_chat_participant"),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"], name="chat_participant_user_idx"),
            models.Index(fields=["chat", "is_active"], name="chat_participant_chat_idx"),
        ]

    def __str__(self) -> str:
        return f"ChatParticipant(chat={self.chat_id}, user={self.user_id})"


class Message(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_chat_messages",
    )
    text = models.TextField()
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["chat", "created_at"], name="chat_message_time_idx"),
        ]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_text = None

        if not is_new:
            old_text = Message.objects.filter(pk=self.pk).values_list("text", flat=True).first()

        super().save(*args, **kwargs)

        if not is_new and old_text is not None and old_text != self.text and not self.is_edited:
            self.is_edited = True
            super().save(update_fields=["is_edited", "updated_at"])

        Chat.objects.filter(pk=self.chat_id).update(last_message_at=self.created_at)

    def __str__(self) -> str:
        return f"Message#{self.pk} chat={self.chat_id} sender={self.sender_id}"
