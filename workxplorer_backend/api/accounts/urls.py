from django.urls import path

from .views import (
    AnalyticsView,
    ChangeRoleView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    RegisterView,
    ResendVerifyView,
    ResetPasswordView,
    SendPhoneOTPView,
    UpdateMeView,
    VerifyEmailView,
    VerifyPhoneOTPView,
    UpdateFCMTokenView,
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
    path("me/analytics/", AnalyticsView.as_view()),
    # Roles
    path("change-role/", ChangeRoleView.as_view()),
    # Password reset
    path("forgot-password/", ForgotPasswordView.as_view()),
    path("reset-password/", ResetPasswordView.as_view()),
    # FCM
    path("fcm-token/", UpdateFCMTokenView.as_view()),
]
