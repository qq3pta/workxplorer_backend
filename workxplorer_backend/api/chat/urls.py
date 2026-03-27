from django.urls import path

from .views import (
    ChatInfoView,
    ChatListView,
    ChatMessagesView,
    ChatPingView,
    ChatReadView,
    GroupCreateView,
    GroupInviteLinkView,
    JoinByLinkView,
    OpenPersonalChatView,
    UserSearchView,
)

urlpatterns = [
    path("ping/", ChatPingView.as_view(), name="chat-ping"),
    path("groups/", GroupCreateView.as_view(), name="chat-group-create"),
    path(
        "groups/<str:chat_id>/invite-link/", GroupInviteLinkView.as_view(), name="chat-invite-link"
    ),
    path("join-by-link/", JoinByLinkView.as_view(), name="chat-join-by-link"),
    path("personal/", OpenPersonalChatView.as_view(), name="chat-open-personal"),
    path("users/search/", UserSearchView.as_view(), name="chat-user-search"),
    path("chats/", ChatListView.as_view(), name="chat-list"),
    path("chats/<str:chat_id>/info/", ChatInfoView.as_view(), name="chat-info"),
    path("chats/<str:chat_id>/messages/", ChatMessagesView.as_view(), name="chat-messages"),
    path("chats/<str:chat_id>/read/", ChatReadView.as_view(), name="chat-read"),
]
