from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("registrieren/", views.register, name="register"),
    path(
        "anmelden/",
        views.SecureLoginView.as_view(),
        name="login",
    ),
    path("abmelden/", auth_views.LogoutView.as_view(), name="logout"),
    path("profil/", views.profile, name="profile"),
    path("profil/deaktivieren/", views.deactivate, name="deactivate"),
    path("verifizieren/erneut/", views.resend_verification, name="resend_verification"),
    path("verifizieren/<uidb64>/<token>/", views.verify_email, name="verify"),
    path("2fa/einrichten/", views.two_factor_setup, name="two_factor_setup"),
    path("2fa/qr/", views.two_factor_qr, name="two_factor_qr"),
    path("2fa/pruefen/", views.two_factor_challenge, name="two_factor_challenge"),
    path("2fa/deaktivieren/", views.two_factor_disable, name="two_factor_disable"),
    path(
        "passwort-vergessen/",
        views.AuditedPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "passwort-vergessen/gesendet/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "passwort-neu/<uidb64>/<token>/",
        views.AuditedPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "passwort-neu/fertig/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path(
        "passwort-aendern/",
        views.AuditedPasswordChangeView.as_view(),
        name="password_change",
    ),
]
