from django.urls import path

from .views import (
    ChatPingView,
    GroupCreateView,
    GroupInviteLinkView,
    JoinByLinkView,
    UserSearchView,
)

urlpatterns = [
    path("ping/", ChatPingView.as_view(), name="chat-ping"),
    path("groups/", GroupCreateView.as_view(), name="chat-group-create"),
    path("groups/<int:chat_id>/invite-link/", GroupInviteLinkView.as_view(), name="chat-invite-link"),
    path("join-by-link/", JoinByLinkView.as_view(), name="chat-join-by-link"),
    path("users/search/", UserSearchView.as_view(), name="chat-user-search"),
]
