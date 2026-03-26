from django.contrib import admin

from .models import Chat, ChatParticipant, Message


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_type", "title", "created_by", "last_message_at", "created_at")
    list_filter = ("chat_type", "allow_join_by_link", "created_at")
    search_fields = ("title", "created_by__username", "created_by__email")


@admin.register(ChatParticipant)
class ChatParticipantAdmin(admin.ModelAdmin):
    list_display = ("id", "chat", "user", "is_admin", "is_active", "joined_at")
    list_filter = ("is_admin", "is_active", "joined_at")
    search_fields = ("chat__title", "user__username", "user__email", "user__phone")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "chat", "sender", "is_edited", "created_at")
    list_filter = ("is_edited", "created_at")
    search_fields = ("chat__title", "sender__username", "sender__email", "text")
