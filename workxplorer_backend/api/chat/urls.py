from django.urls import path

from .views import (
    ChatListView,
    ChatMessagesView,
    ChatPingView,
    ChatReadView,
    GroupCreateView,
    GroupInviteLinkView,
    JoinByLinkView,
    UserSearchView,
)

urlpatterns = [
    path("ping/", ChatPingView.as_view(), name="chat-ping"),
    path("groups/", GroupCreateView.as_view(), name="chat-group-create"),
    path(
        "groups/<str:chat_id>/invite-link/", GroupInviteLinkView.as_view(), name="chat-invite-link"
    ),
    path("join-by-link/", JoinByLinkView.as_view(), name="chat-join-by-link"),
    path("users/search/", UserSearchView.as_view(), name="chat-user-search"),
    path("chats/", ChatListView.as_view(), name="chat-list"),
    path("chats/<str:chat_id>/messages/", ChatMessagesView.as_view(), name="chat-messages"),
    path("chats/<str:chat_id>/read/", ChatReadView.as_view(), name="chat-read"),
]
