from django.urls import path

from .views import (
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
    AnalyticsView,
)

urlpatterns = [
    # WhatsApp-OTP (телефон)
    path("send-otp/phone/", SendPhoneOTPView.as_view()),
    path("verify-otp/phone/", VerifyPhoneOTPView.as_view()),
    # Остальные auth-ручки
    path("register/", RegisterView.as_view()),
    path("resend-verify/", ResendVerifyView.as_view()),
    path("verify-email/", VerifyEmailView.as_view()),
    path("login/", LoginView.as_view()),
    path("refresh/", RefreshView.as_view()),
    path("me/", MeView.as_view()),
    path("me/update/", UpdateMeView.as_view()),
    path("forgot-password/", ForgotPasswordView.as_view()),
    path("reset-password/", ResetPasswordView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("change-role/", ChangeRoleView.as_view()),
    path("me/analytics/", AnalyticsView.as_view()),
]
