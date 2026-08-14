import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.audit.models import AuditEvent
from apps.catalog.models import LegoSet

from .models import AccountSession, PendingEmailChange, RecoveryCode
from .services import create_email_change
from .tokens import email_verification_token
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
        get_user_model().objects.create_user(
            "pending", "pending@example.test", "A-very-long-password-123"
        )
        response = self.client.post(
            reverse("accounts:resend_verification"), {"email": "pending@example.test"}
        )
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

    def test_email_verification_is_single_use_and_honors_expiry(self):
        user = get_user_model().objects.create_user(
            "verify-token", "verify-token@example.test", "A-very-long-password-123"
        )
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)
        url = reverse("accounts:verify", args=[uid, token])
        self.assertRedirects(self.client.get(url), reverse("accounts:login"))
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertEqual(self.client.get(url).status_code, 400)

        expired = get_user_model().objects.create_user(
            "expired-token", "expired-token@example.test", "A-very-long-password-123"
        )
        expired_uid = urlsafe_base64_encode(force_bytes(expired.pk))
        expired_token = email_verification_token.make_token(expired)
        with override_settings(EMAIL_VERIFICATION_TIMEOUT=-1):
            response = self.client.get(
                reverse("accounts:verify", args=[expired_uid, expired_token])
            )
        self.assertEqual(response.status_code, 400)

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
            username,
            f"{username}@example.test",
            "A-very-long-password-123",
            email_verified=True,
            totp_enabled=True,
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
        for value in (
            "000000",
            code_for(secret, time.time() - 90),
            code_for(secret, time.time() + 90),
        ):
            response = self.client.post(reverse("accounts:two_factor_challenge"), {"code": value})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_recovery_code_is_one_use_and_invalid_code_is_rejected(self):
        user, _ = self._totp_user("recovery")
        plain = RecoveryCode.generate_for(user)[0]
        self._start_challenge(user)
        response = self.client.post(reverse("accounts:two_factor_challenge"), {"code": plain})
        self.assertRedirects(response, reverse("dashboard"))
        self.client.post(reverse("accounts:logout"))
        self._start_challenge(user)
        response = self.client.post(reverse("accounts:two_factor_challenge"), {"code": plain})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_disabled_unconfirmed_and_unknown_user_challenges_do_not_authenticate(self):
        user = get_user_model().objects.create_user(
            "disabled-2fa",
            "disabled-2fa@example.test",
            "A-very-long-password-123",
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
            "audit-user",
            "audit-user@example.test",
            "A-very-long-password-123",
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
        self.assertTrue(
            AuditEvent.objects.filter(action="account.login_success", actor=user).exists()
        )
        self.assertTrue(AuditEvent.objects.filter(action="account.logout", actor=user).exists())
        for _ in range(5):
            self.client.post(reverse("accounts:password_reset"), {"email": "unknown@example.test"})
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "unknown@example.test"}
        )
        self.assertEqual(response.status_code, 429)

    def test_duplicate_username_and_open_redirect_are_blocked(self):
        get_user_model().objects.create_user(
            "taken", "taken@example.test", "A-very-long-password-123"
        )
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "taken",
                "email": "other@example.test",
                "password1": "A-very-long-password-123",
                "password2": "A-very-long-password-123",
            },
        )
        self.assertContains(response, "bereits vergeben")
        user = get_user_model().objects.create_user(
            "redirect", "redirect@example.test", "A-very-long-password-123", email_verified=True
        )
        response = self.client.post(
            reverse("accounts:login") + "?next=https://evil.example/",
            {"username": user.username, "password": "A-very-long-password-123"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_inactive_user_cannot_login(self):
        user = get_user_model().objects.create_user(
            "inactive",
            "inactive@example.test",
            "A-very-long-password-123",
            email_verified=True,
            is_active=False,
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "A-very-long-password-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_change_keeps_old_address_until_single_use_confirmation(self):
        user = get_user_model().objects.create_user(
            "change", "old@example.test", "A-very-long-password-123", email_verified=True
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:change_email"),
            {"email": "NEW@Example.Test", "password": "A-very-long-password-123"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.test")
        self.assertTrue(PendingEmailChange.objects.filter(user=user).exists())
        url = mail.outbox[-1].body.splitlines()[3]
        response = self.client.get(url)
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.email, "new@example.test")
        self.assertTrue(user.email_verified)
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_expired_email_change_is_rejected(self):
        user = get_user_model().objects.create_user(
            "expired-email", "old2@example.test", "A-very-long-password-123", email_verified=True
        )
        self.client.force_login(user)
        pending = create_email_change(self.client.request().wsgi_request, user, "new2@example.test")
        pending.expires_at = timezone.now() - timedelta(seconds=1)
        pending.save(update_fields=["expires_at"])
        url = mail.outbox[-1].body.splitlines()[3]
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_placeholder_email_never_receives_password_reset(self):
        get_user_model().objects.create_user(
            "legacy",
            "legacy-7@invalid.local",
            "A-very-long-password-123",
            email_verified=True,
            legacy_id=7,
        )
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "legacy-7@invalid.local"}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(mail.outbox, [])

    def test_password_change_keeps_current_session_and_audits(self):
        user = get_user_model().objects.create_user(
            "password", "password@example.test", "A-very-long-password-123", email_verified=True
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "A-very-long-password-123",
                "new_password1": "A-new-very-long-password-456",
                "new_password2": "A-new-very-long-password-456",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(str(self.client.session["_auth_user_id"]), str(user.pk))
        self.assertTrue(
            AuditEvent.objects.filter(action="account.password_changed", actor=user).exists()
        )

    def test_sessions_are_scoped_and_foreign_revoke_is_404(self):
        user = get_user_model().objects.create_user(
            "sessions", "sessions@example.test", "A-very-long-password-123", email_verified=True
        )
        other = get_user_model().objects.create_user(
            "other-session",
            "other-session@example.test",
            "A-very-long-password-123",
            email_verified=True,
        )
        self.client.force_login(user)
        self.client.get(reverse("accounts:sessions"), HTTP_USER_AGENT="Current browser")
        store = SessionStore()
        store.create()
        foreign = AccountSession.objects.create(
            user=other, session_key=store.session_key, user_agent="Foreign"
        )
        self.assertEqual(
            self.client.post(reverse("accounts:revoke_session", args=[foreign.pk])).status_code, 404
        )
        self.assertTrue(AccountSession.objects.filter(pk=foreign.pk).exists())

    def test_revoke_all_others_preserves_current_session(self):
        user = get_user_model().objects.create_user(
            "revoke", "revoke@example.test", "A-very-long-password-123", email_verified=True
        )
        self.client.force_login(user)
        self.client.get(reverse("accounts:sessions"))
        store = SessionStore()
        store["_auth_user_id"] = str(user.pk)
        store.save()
        other = AccountSession.objects.create(user=user, session_key=store.session_key)
        response = self.client.post(
            reverse("accounts:revoke_other_sessions"), {"password": "A-very-long-password-123"}
        )
        self.assertRedirects(response, reverse("accounts:sessions"))
        self.assertFalse(AccountSession.objects.filter(pk=other.pk).exists())
        self.assertIn("_auth_user_id", self.client.session)

    def test_account_delete_requires_post_confirmation_and_preserves_relations(self):
        user = get_user_model().objects.create_user(
            "delete-me", "delete@example.test", "A-very-long-password-123", email_verified=True
        )
        lego_set = LegoSet.objects.create(owner=user, set_number="1-1", name="Owned")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:deactivate")).status_code, 405)
        self.assertEqual(
            self.client.post(
                reverse("accounts:deactivate"), {"password": "wrong", "confirmation": "LÖSCHEN"}
            ).status_code,
            400,
        )
        response = self.client.post(
            reverse("accounts:deactivate"),
            {"password": "A-very-long-password-123", "confirmation": "LÖSCHEN"},
        )
        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        lego_set.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertTrue(user.email.endswith("@invalid.local"))
        self.assertEqual(lego_set.owner_id, user.pk)

    def test_account_delete_enforces_csrf(self):
        user = get_user_model().objects.create_user(
            "csrf-delete", "csrf@example.test", "A-very-long-password-123", email_verified=True
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        self.assertEqual(
            client.post(
                reverse("accounts:deactivate"),
                {"password": "A-very-long-password-123", "confirmation": "LÖSCHEN"},
            ).status_code,
            403,
        )

    def test_normal_user_cannot_access_admin_but_staff_can(self):
        user = get_user_model().objects.create_user(
            "plain", "plain@example.test", "A-very-long-password-123", email_verified=True
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        staff = get_user_model().objects.create_user(
            "brickadmin",
            "admin@example.test",
            "A-very-long-password-123",
            email_verified=True,
            is_staff=True,
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
