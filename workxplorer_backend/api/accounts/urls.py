from django.urls import path
from .views import (
    RegisterView, ResendVerifyView, VerifyEmailView, LoginView,
    MeView, UpdateMeView, ForgotPasswordView, ResetPasswordView,
)

urlpatterns = [
    path("register/", RegisterView.as_view()),
    path("resend-verify/", ResendVerifyView.as_view()),
    path("verify-email/", VerifyEmailView.as_view()),
    path("login/", LoginView.as_view()),
    path("me/", MeView.as_view()),
    path("me/update/", UpdateMeView.as_view()),
    path("forgot-password/", ForgotPasswordView.as_view()),
    path("reset-password/", ResetPasswordView.as_view()),
]