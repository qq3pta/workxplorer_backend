from django.urls import path


from .views import (
    AvatarView,
    ChangeRoleView,
    DeleteAccountView,
    FleetCandidateListView,
    FleetIncomingInviteListView,
    FleetInviteAcceptView,
    FleetInviteDeclineView,
    FleetInviteView,
    FleetListView,
    FleetMembershipDeleteView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    RegisterView,
    ResendVerifyView,
    ChangePasswordView,
    SendPhoneOTPView,
    UpdateFCMTokenView,
    UpdateMeView,
    VerifyEmailView,
    VerifyPhoneOTPView,
    dashboard_stats,
    SendEmailVerifyFromProfileView,
    VerifyEmailFromProfileView,
)

urlpatterns = [
    # WhatsApp-OTP (телефон)
    path("send-otp/phone/", SendPhoneOTPView.as_view()),
    path("verify-otp/phone/", VerifyPhoneOTPView.as_view()),
    # Auth
    path("register/", RegisterView.as_view()),
    path("resend-verify/", ResendVerifyView.as_view()),
    path("verify-email/", VerifyEmailView.as_view()),
    path("login/", LoginView.as_view()),
    path("refresh/", RefreshView.as_view()),
    path("logout/", LogoutView.as_view()),
    # Profile
    path("me/", MeView.as_view()),
    path("me/update/", UpdateMeView.as_view()),
    path("me/avatar/", AvatarView.as_view()),
    path("me/delete/", DeleteAccountView.as_view()),
    # Roles
    path("change-role/", ChangeRoleView.as_view()),
    # Password reset
    path("forgot-password/", ForgotPasswordView.as_view()),
    path("change-password/", ChangePasswordView.as_view()),
    # FCM
    path("fcm-token/", UpdateFCMTokenView.as_view()),
    # Fleet / park
    path("park/", FleetListView.as_view(), name="fleet-list"),
    path("park/candidates/", FleetCandidateListView.as_view(), name="fleet-candidates"),
    path("park/invite/", FleetInviteView.as_view(), name="fleet-invite"),
    path("park/incoming/", FleetIncomingInviteListView.as_view(), name="fleet-incoming"),
    path("park/invitations/<int:pk>/accept/", FleetInviteAcceptView.as_view(), name="fleet-accept"),
    path(
        "park/invitations/<int:pk>/decline/", FleetInviteDeclineView.as_view(), name="fleet-decline"
    ),
    path("park/<int:pk>/", FleetMembershipDeleteView.as_view(), name="fleet-delete"),
    path("dashboard-stats/", dashboard_stats, name="dashboard-stats"),
    # Email verification from profile
    path("me/email/send/", SendEmailVerifyFromProfileView.as_view()),
    path("me/email/verify/", VerifyEmailFromProfileView.as_view()),
]
