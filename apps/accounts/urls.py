from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("profil/rebrickable/speichern/", views.rebrickable_save, name="rebrickable_save"),
    path("profil/rebrickable/testen/", views.rebrickable_test, name="rebrickable_test"),
    path("profil/rebrickable/entfernen/", views.rebrickable_remove, name="rebrickable_remove"),
    path("registrieren/", views.register, name="register"),
    path(
        "anmelden/",
        views.SecureLoginView.as_view(),
        name="login",
    ),
    path("abmelden/", auth_views.LogoutView.as_view(), name="logout"),
    path("profil/", views.account_profile, name="profile"),
    path("profil/e-mail-aendern/", views.change_email, name="change_email"),
    path(
        "profil/e-mail-bestaetigen/<uuid:pk>/<str:token>/",
        views.confirm_email_change,
        name="confirm_email_change",
    ),
    path("profil/sitzungen/", views.sessions, name="sessions"),
    path("profil/sitzungen/<uuid:pk>/beenden/", views.revoke_session_view, name="revoke_session"),
    path(
        "profil/sitzungen/andere-beenden/",
        views.revoke_other_sessions,
        name="revoke_other_sessions",
    ),
    path("profil/konto-loeschen/", views.delete_account, name="delete_account"),
    path("profil/deaktivieren/", views.deactivate_account, name="deactivate_account"),
    path("profil/deaktivieren/bestaetigen/", views.anonymize_account, name="deactivate"),
    path("profil/konto-loeschen/bestaetigen/", views.permanently_delete_account, name="permanent_delete"),
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
