from django.urls import path

from .views import (
    ChatInfoView,
    ChatListView,
    ChatMessagesView,
    ChatPingView,
    ChatReadView,
    GroupAddParticipantsView,
    GroupCreateView,
    GroupDeleteView,
    GroupInviteLinkView,
    GroupLeaveView,
    JoinByLinkView,
    OpenPersonalChatView,
    PersonalChatDeleteView,
    UserSearchView,
)

urlpatterns = [
    path("ping/", ChatPingView.as_view(), name="chat-ping"),
    path("groups/", GroupCreateView.as_view(), name="chat-group-create"),
    path(
        "groups/<str:chat_id>/participants/",
        GroupAddParticipantsView.as_view(),
        name="chat-group-add-participants",
    ),
    path(
        "groups/<str:chat_id>/invite-link/", GroupInviteLinkView.as_view(), name="chat-invite-link"
    ),
    path("groups/<str:chat_id>/leave/", GroupLeaveView.as_view(), name="chat-group-leave"),
    path("groups/<str:chat_id>/", GroupDeleteView.as_view(), name="chat-group-delete"),
    path("join-by-link/", JoinByLinkView.as_view(), name="chat-join-by-link"),
    path("personal/", OpenPersonalChatView.as_view(), name="chat-open-personal"),
    path(
        "chats/<str:chat_id>/personal/",
        PersonalChatDeleteView.as_view(),
        name="chat-personal-delete",
    ),
    path("users/search/", UserSearchView.as_view(), name="chat-user-search"),
    path("chats/", ChatListView.as_view(), name="chat-list"),
    path("chats/<str:chat_id>/info/", ChatInfoView.as_view(), name="chat-info"),
    path("chats/<str:chat_id>/messages/", ChatMessagesView.as_view(), name="chat-messages"),
    path("chats/<str:chat_id>/read/", ChatReadView.as_view(), name="chat-read"),
]
