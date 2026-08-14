import time

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent

from .models import RecoveryCode
from .totp import code_for, decrypt_secret, encrypt_secret, generate_secret


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_registration_never_creates_admin_and_sends_verification(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "email": "New@Example.Test",
                "password1": "A-very-long-password-123",
                "password2": "A-very-long-password-123",
            },
        )
        self.assertRedirects(response, reverse("accounts:login"))
        user = get_user_model().objects.get(username="newuser")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.email_verified)
        self.assertEqual(user.email, "new@example.test")
        self.assertEqual(len(mail.outbox), 1)

    def test_email_is_case_insensitive_unique(self):
        get_user_model().objects.create_user(
            "first", "same@example.test", "A-very-long-password-123"
        )
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "second",
                "email": "SAME@example.test",
                "password1": "A-very-long-password-123",
                "password2": "A-very-long-password-123",
            },
        )
        self.assertContains(response, "bereits ein Konto")

    def test_logout_is_post_only(self):
        user = get_user_model().objects.create_user(
            "someone", "some@example.test", "A-very-long-password-123"
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)

    def test_unverified_user_cannot_login(self):
        get_user_model().objects.create_user(
            "pending", "pending@example.test", "A-very-long-password-123"
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pending", "password": "A-very-long-password-123"},
        )
        self.assertContains(response, "bestätige zuerst")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unverified_user_can_request_neutral_resend_without_login(self):
        get_user_model().objects.create_user("pending", "pending@example.test", "A-very-long-password-123")
        response = self.client.post(reverse("accounts:resend_verification"), {"email": "pending@example.test"})
        from apps.audit.models import AuditEvent
        event = AuditEvent.objects.get(action="account.email_verification_resent")
        self.assertEqual(event.details, {"result": "sent"})
        self.assertNotIn("token", str(event.details).lower())
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertEqual(len(mail.outbox), 1)

    def test_verified_user_can_login(self):
        user = get_user_model().objects.create_user(
            "verified", "verified@example.test", "A-very-long-password-123"
        )
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "verified", "password": "A-very-long-password-123"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_totp_setup_and_login_challenge(self):
        user = get_user_model().objects.create_user(
            "secured", "secured@example.test", "A-very-long-password-123"
        )
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        self.client.force_login(user)
        self.client.get(reverse("accounts:two_factor_setup"))
        secret = self.client.session["pending_totp_secret"]
        response = self.client.post(
            reverse("accounts:two_factor_setup"), {"code": code_for(secret)}
        )
        self.assertContains(response, "Recovery Codes")
        user.refresh_from_db()
        self.assertTrue(user.totp_enabled)
        self.assertEqual(decrypt_secret(user.totp_secret_encrypted), secret)
        self.client.logout()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "secured", "password": "A-very-long-password-123"},
        )
        self.assertRedirects(response, reverse("accounts:two_factor_challenge"))
        response = self.client.post(
            reverse("accounts:two_factor_challenge"), {"code": code_for(secret)}
        )
        self.assertRedirects(response, reverse("dashboard"))

    def _totp_user(self, username="totp-negative"):
        secret = generate_secret()
        user = get_user_model().objects.create_user(
            username, f"{username}@example.test", "A-very-long-password-123",
            email_verified=True, totp_enabled=True,
            totp_secret_encrypted=encrypt_secret(secret),
        )
        return user, secret

    def _start_challenge(self, user):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "A-very-long-password-123"},
        )
        self.assertRedirects(response, reverse("accounts:two_factor_challenge"))

    def test_wrong_expired_and_future_totp_are_rejected(self):
        user, secret = self._totp_user()
        self._start_challenge(user)
        for value in ("000000", code_for(secret, time.time() - 90), code_for(secret, time.time() + 90)):
            response = self.client.post(
                reverse("accounts:two_factor_challenge"), {"code": value}
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_recovery_code_is_one_use_and_invalid_code_is_rejected(self):
        user, _ = self._totp_user("recovery")
        plain = RecoveryCode.generate_for(user)[0]
        self._start_challenge(user)
        response = self.client.post(
            reverse("accounts:two_factor_challenge"), {"code": plain}
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.client.post(reverse("accounts:logout"))
        self._start_challenge(user)
        response = self.client.post(
            reverse("accounts:two_factor_challenge"), {"code": plain}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_disabled_unconfirmed_and_unknown_user_challenges_do_not_authenticate(self):
        user = get_user_model().objects.create_user(
            "disabled-2fa", "disabled-2fa@example.test", "A-very-long-password-123",
            email_verified=True,
        )
        session = self.client.session
        session["pending_totp_secret"] = generate_secret()
        session["pre_2fa_user_id"] = str(user.pk)
        session.save()
        self.assertRedirects(
            self.client.post(reverse("accounts:two_factor_challenge"), {"code": "000000"}),
            reverse("accounts:login"),
        )
        session = self.client.session
        session["pre_2fa_user_id"] = "999999999"
        session.save()
        self.assertRedirects(
            self.client.get(reverse("accounts:two_factor_challenge")),
            reverse("accounts:login"),
        )

    def test_auth_audit_and_password_reset_rate_limit(self):
        user = get_user_model().objects.create_user(
            "audit-user", "audit-user@example.test", "A-very-long-password-123",
            email_verified=True,
        )
        self.client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "wrong"},
        )
        self.client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "A-very-long-password-123"},
        )
        self.client.post(reverse("accounts:logout"))
        self.assertTrue(AuditEvent.objects.filter(action="account.login_failed").exists())
        self.assertTrue(AuditEvent.objects.filter(action="account.login_success", actor=user).exists())
        self.assertTrue(AuditEvent.objects.filter(action="account.logout", actor=user).exists())
        for _ in range(5):
            self.client.post(reverse("accounts:password_reset"), {"email": "unknown@example.test"})
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "unknown@example.test"}
        )
        self.assertEqual(response.status_code, 429)
