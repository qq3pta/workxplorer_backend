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
    UpdateMeView,
    VerifyEmailView,
)

urlpatterns = [
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
]
