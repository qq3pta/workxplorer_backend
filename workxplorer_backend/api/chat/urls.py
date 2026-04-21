from django.urls import path

from .views import (
    ChatInfoView,
    ChatListView,
    ChatExportView,
    ChatMessageDeleteView,
    ChatMessagesView,
    ChatMuteView,
    ChatPingView,
    ChatReadView,
    GroupAddParticipantsView,
    GroupCreateView,
    GroupDeleteView,
    GroupInviteAcceptDirectView,
    GroupInviteDecisionView,
    GroupInviteLinkView,
    GroupKickMemberView,
    GroupLeaveView,
    GroupTitleUpdateView,
    JoinByLinkView,
    OpenPersonalChatView,
    OrderChatView,
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
        "groups/<str:chat_id>/participants/<int:user_id>/",
        GroupKickMemberView.as_view(),
        name="chat-group-kick-member",
    ),
    path(
        "groups/<str:chat_id>/title/",
        GroupTitleUpdateView.as_view(),
        name="chat-group-title-update",
    ),
    path(
        "groups/<str:chat_id>/invite-link/", GroupInviteLinkView.as_view(), name="chat-invite-link"
    ),
    path(
        "groups/<str:chat_id>/invite/decision/",
        GroupInviteDecisionView.as_view(),
        name="chat-group-invite-decision",
    ),
    path(
        "groups/<str:chat_id>/invite/accept/",
        GroupInviteAcceptDirectView.as_view(),
        name="chat-group-invite-accept-direct",
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
    path("chats/<str:chat_id>/export/", ChatExportView.as_view(), name="chat-export"),
    path("chats/<str:chat_id>/messages/", ChatMessagesView.as_view(), name="chat-messages"),
    path(
        "chats/<str:chat_id>/messages/<int:message_id>/",
        ChatMessageDeleteView.as_view(),
        name="chat-message-delete",
    ),
    path("chats/<str:chat_id>/mute/", ChatMuteView.as_view(), name="chat-mute"),
    path("chats/<str:chat_id>/read/", ChatReadView.as_view(), name="chat-read"),
    path("orders/<int:order_id>/chat/", OrderChatView.as_view(), name="chat-order-chat"),
]
