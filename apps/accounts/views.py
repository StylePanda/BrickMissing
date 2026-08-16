import hashlib
import hmac
import uuid

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetView,
)
from django.core.cache import cache
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.core.client_ip import client_ip
from apps.core.rate_limit import limited

from .account_deletion import (
    AccountDeletionFileError,
    delete_account_and_data,
)
from .account_deletion import (
    anonymize_account as anonymize_account_service,
)
from .forms import (
    AccountDeactivateForm,
    AccountDeleteForm,
    DeliverablePasswordResetForm,
    EmailChangeForm,
    RebrickableApiKeyForm,
    RegistrationForm,
    VerifiedAuthenticationForm,
)
from .models import PendingEmailChange, RecoveryCode, User
from .services import create_email_change, revoke_session, send_verification_email
from .tokens import email_verification_token
from .totp import (
    decrypt_secret,
    encrypt_secret,
    generate_secret,
    provisioning_uri,
    qr_svg,
    verify_code,
)


class SecureLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = VerifiedAuthenticationForm

    def form_valid(self, form):
        user = form.get_user()
        if user.totp_enabled:
            self.request.session.flush()
            self.request.session["pre_2fa_user_id"] = str(user.pk)
            self.request.session["pre_2fa_backend"] = user.backend
            return redirect("accounts:two_factor_challenge")
        return super().form_valid(form)


def _client_key(request, scope: str) -> str:
    return f"rate:{scope}:{client_ip(request)}"


def _limited(request, scope: str, limit: int, seconds: int) -> bool:
    key = _client_key(request, scope)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, seconds)
        count = 1
    return count > limit


def register(request):
    if request.method == "POST" and _limited(request, "register", 10, 3600):
        return HttpResponse("Zu viele Anfragen. Bitte später erneut versuchen.", status=429)
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_active = True
        user.email_verified = False
        user.save()
        send_verification_email(request, user)
        AuditEvent.objects.create(
            action="account.registered", target_user=user, request_id=request.request_id
        )
        messages.success(request, "Konto erstellt. Bitte bestätige deine E-Mail-Adresse.")
        return redirect("accounts:login")
    return render(request, "accounts/register.html", {"form": form})


def verify_email(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        raise Http404 from None
    if not email_verification_token.check_token(user, token):
        return render(request, "accounts/verification_invalid.html", status=400)
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified", "updated_at"])
        AuditEvent.objects.create(
            action="account.email_verified", target_user=user, request_id=request.request_id
        )
    messages.success(request, "E-Mail-Adresse bestätigt. Du kannst dich jetzt anmelden.")
    return redirect("accounts:login")


@require_POST
def resend_verification(request):
    if _limited(request, "verify", 3, 3600):
        return HttpResponse("Zu viele Anfragen. Bitte später erneut versuchen.", status=429)
    email = request.POST.get("email", "").strip().casefold()
    user = (
        request.user
        if request.user.is_authenticated
        else User.objects.filter(email__iexact=email, is_active=True).first()
    )
    result = "not_required_or_unknown"
    if user and not user.email_verified:
        send_verification_email(request, user)
        result = "sent"
    AuditEvent.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        target_user=user,
        action="account.email_verification_resent",
        details={"result": result},
        remote_address=client_ip(request),
        request_id=request.request_id,
    )
    messages.success(request, "Falls erforderlich, wurde eine Bestätigungsmail versendet.")
    return redirect("accounts:profile" if request.user.is_authenticated else "accounts:login")


@login_required
def profile(request):
    form = EmailChangeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not request.user.check_password(form.cleaned_data["password"]):
            form.add_error("password", "Das Passwort ist nicht korrekt.")
        elif (
            User.objects.filter(email__iexact=form.cleaned_data["email"])
            .exclude(pk=request.user.pk)
            .exists()
        ):
            form.add_error("email", "Diese E-Mail-Adresse wird bereits verwendet.")
        else:
            request.user.email = form.cleaned_data["email"]
            request.user.email_verified = False
            request.user.save(update_fields=["email", "email_verified", "updated_at"])
            send_verification_email(request, request.user)
            AuditEvent.objects.create(
                actor=request.user,
                target_user=request.user,
                action="account.email_changed",
                request_id=request.request_id,
            )
            messages.success(request, "E-Mail geändert. Bitte erneut bestätigen.")
            return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {"form": form, "rebrickable_form": RebrickableApiKeyForm()},
    )


@login_required
@require_POST
def rebrickable_save(request):
    form = RebrickableApiKeyForm(request.POST)
    if form.is_valid():
        request.user.rebrickable_api_key_encrypted = encrypt_secret(form.cleaned_data["api_key"])
        request.user.save(update_fields=["rebrickable_api_key_encrypted", "updated_at"])
        AuditEvent.objects.create(
            actor=request.user, target_user=request.user,
            action="integration.rebrickable_key_saved", request_id=request.request_id,
        )
        messages.success(request, "Rebrickable API-Key wurde sicher gespeichert.")
    else:
        messages.error(request, "Der Rebrickable API-Key ist ungültig.")
    return redirect("accounts:profile")


@login_required
@require_POST
def rebrickable_test(request):
    from apps.integrations.services import RebrickableError, test_rebrickable_connection

    if limited(request, "rebrickable-test", 10, 3600, per_user=True):
        return HttpResponse("Zu viele Anfragen. Bitte später erneut versuchen.", status=429)
    if not request.user.rebrickable_api_key_encrypted:
        messages.error(request, "Es ist kein Rebrickable API-Key hinterlegt.")
        return redirect("accounts:profile")
    try:
        test_rebrickable_connection(decrypt_secret(request.user.rebrickable_api_key_encrypted))
    except RebrickableError as exc:
        if exc.code == "authentication":
            messages.error(request, "Der Rebrickable API-Key ist ungültig.")
        else:
            messages.error(request, "Rebrickable ist momentan nicht erreichbar. Bitte versuche es später erneut.")
    else:
        messages.success(request, "Rebrickable-Verbindung erfolgreich.")
    return redirect("accounts:profile")


@login_required
@require_POST
def rebrickable_remove(request):
    request.user.rebrickable_api_key_encrypted = ""
    request.user.save(update_fields=["rebrickable_api_key_encrypted", "updated_at"])
    AuditEvent.objects.create(
        actor=request.user, target_user=request.user,
        action="integration.rebrickable_key_removed", request_id=request.request_id,
    )
    messages.success(request, "Rebrickable-Verbindung wurde entfernt.")
    return redirect("accounts:profile")


@login_required
@require_POST
def deactivate(request):
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "Das Passwort ist nicht korrekt.")
        return redirect("accounts:profile")
    user = request.user
    AuditEvent.objects.create(
        actor=user, target_user=user, action="account.deactivated", request_id=request.request_id
    )
    user.is_active = False
    user.deactivated_at = timezone.now()
    user.save(update_fields=["is_active", "deactivated_at", "updated_at"])
    logout(request)
    return redirect("accounts:login")


@login_required
def two_factor_setup(request):
    if request.user.totp_enabled:
        return redirect("accounts:profile")
    secret = request.session.get("pending_totp_secret") or generate_secret()
    request.session["pending_totp_secret"] = secret
    if request.method == "POST":
        if verify_code(secret, request.POST.get("code", "").strip()):
            request.user.totp_secret_encrypted = encrypt_secret(secret)
            request.user.totp_enabled = True
            request.user.save(update_fields=["totp_secret_encrypted", "totp_enabled", "updated_at"])
            request.user.recovery_codes.all().delete()
            codes = RecoveryCode.generate_for(request.user)
            request.session.pop("pending_totp_secret", None)
            AuditEvent.objects.create(
                actor=request.user,
                target_user=request.user,
                action="account.2fa_enabled",
                request_id=request.request_id,
            )
            return render(request, "accounts/recovery_codes.html", {"codes": codes})
        messages.error(request, "Der Bestätigungscode ist ungültig.")
    return render(request, "accounts/two_factor_setup.html", {"secret": secret})


@login_required
def two_factor_qr(request):
    secret = request.session.get("pending_totp_secret")
    if not secret:
        raise Http404
    data = qr_svg(provisioning_uri(secret, request.user.username))
    return HttpResponse(data, content_type="image/svg+xml")


def two_factor_challenge(request):
    user_id = request.session.get("pre_2fa_user_id")
    if not user_id:
        return redirect("accounts:login")
    try:
        user = User.objects.get(pk=user_id, is_active=True, totp_enabled=True)
    except User.DoesNotExist:
        request.session.flush()
        return redirect("accounts:login")
    if request.method == "POST":
        rate_key = f"2fa:{user.pk}:{client_ip(request)}"
        attempts = cache.get(rate_key, 0)
        if attempts >= 5:
            messages.error(request, "Zu viele Versuche. Bitte später erneut versuchen.")
            return render(request, "accounts/two_factor_challenge.html", status=429)
        value = request.POST.get("code", "").strip().replace("-", "")
        valid = verify_code(decrypt_secret(user.totp_secret_encrypted), value)
        if not valid:
            from django.utils import timezone

            recovery = user.recovery_codes.filter(
                digest=RecoveryCode.digest_code(value.upper()), used_at__isnull=True
            ).first()
            if recovery:
                recovery.used_at = timezone.now()
                recovery.save(update_fields=["used_at"])
                AuditEvent.objects.create(
                    actor=user,
                    target_user=user,
                    action="account.recovery_code_used",
                    request_id=request.request_id,
                )
                valid = True
        if valid:
            cache.delete(rate_key)
            backend = request.session.get(
                "pre_2fa_backend", "django.contrib.auth.backends.ModelBackend"
            )
            request.session.flush()
            login(request, user, backend=backend)
            AuditEvent.objects.create(
                actor=user,
                target_user=user,
                action="account.2fa_login",
                request_id=request.request_id,
            )
            return redirect("dashboard")
        cache.set(rate_key, attempts + 1, 300)
        messages.error(request, "Code ungültig.")
    return render(request, "accounts/two_factor_challenge.html")


@login_required
@require_POST
def two_factor_disable(request):
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "Das Passwort ist nicht korrekt.")
        return redirect("accounts:profile")
    request.user.totp_enabled = False
    request.user.totp_secret_encrypted = ""
    request.user.save(update_fields=["totp_enabled", "totp_secret_encrypted", "updated_at"])
    request.user.recovery_codes.all().delete()
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="account.2fa_disabled",
        request_id=request.request_id,
    )
    messages.success(request, "Zwei-Faktor-Authentifizierung deaktiviert.")
    return redirect("accounts:profile")


class AuditedPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    form_class = DeliverablePasswordResetForm

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST" and limited(request, "password-reset", 5, 3600):
            return HttpResponse("Zu viele Anfragen. Bitte später erneut versuchen.", status=429)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        AuditEvent.objects.create(
            action="account.password_reset_requested",
            remote_address=client_ip(self.request),
            request_id=self.request.request_id,
        )
        return super().form_valid(form)


class AuditedPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        AuditEvent.objects.create(
            target_user=self.user,
            action="account.password_reset_completed",
            remote_address=client_ip(self.request),
            request_id=self.request.request_id,
        )
        return response


class AuditedPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change_form.html"
    success_url = "/konto/profil/"

    def form_valid(self, form):
        response = super().form_valid(form)
        AuditEvent.objects.create(
            actor=self.request.user,
            target_user=self.request.user,
            action="account.password_changed",
            request_id=self.request.request_id,
        )
        messages.success(self.request, "Passwort erfolgreich geändert.")
        return response


# Account-management views are defined together so their security invariants stay explicit.
@login_required
def account_profile(request):
    pending = (
        request.user.pending_email_changes.filter(used_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    return render(
        request, "accounts/profile.html",
        {"pending_email_change": pending, "rebrickable_form": RebrickableApiKeyForm()},
    )


@login_required
def change_email(request):
    form = EmailChangeForm(request.POST or None)
    if request.method == "POST" and _limited(request, "email-change", 5, 3600):
        return HttpResponse("Zu viele Anfragen. Bitte später erneut versuchen.", status=429)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        if not request.user.check_password(form.cleaned_data["password"]):
            form.add_error("password", "Das Passwort ist nicht korrekt.")
        elif email == request.user.email:
            form.add_error("email", "Das ist bereits deine aktuelle E-Mail-Adresse.")
        elif User.objects.filter(email__iexact=email).exclude(pk=request.user.pk).exists():
            form.add_error("email", "Diese E-Mail-Adresse wird bereits verwendet.")
        else:
            pending = create_email_change(request, request.user, email)
            AuditEvent.objects.create(
                actor=request.user,
                target_user=request.user,
                action="account.email_change_started",
                entity_type="pending_email_change",
                entity_id=str(pending.pk),
                request_id=request.request_id,
            )
            messages.success(request, "Bestätigungs-E-Mail an die neue Adresse gesendet.")
            return redirect("accounts:profile")
    return render(request, "accounts/change_email.html", {"form": form})


def confirm_email_change(request, pk, token):
    try:
        pending_id = uuid.UUID(str(pk))
    except ValueError:
        raise Http404 from None
    with transaction.atomic():
        pending = (
            PendingEmailChange.objects.select_for_update()
            .select_related("user")
            .filter(pk=pending_id)
            .first()
        )
        digest = hashlib.sha256(token.encode()).hexdigest()
        if (
            not pending
            or not pending.is_valid
            or not hmac.compare_digest(pending.token_digest, digest)
        ):
            return render(request, "accounts/verification_invalid.html", status=400)
        if User.objects.filter(email__iexact=pending.email).exclude(pk=pending.user_id).exists():
            pending.used_at = timezone.now()
            pending.save(update_fields=["used_at"])
            return render(request, "accounts/verification_invalid.html", status=400)
        user = pending.user
        user.email = pending.email
        user.email_verified = True
        user.save(update_fields=["email", "email_verified", "updated_at"])
        pending.used_at = timezone.now()
        pending.save(update_fields=["used_at"])
        AuditEvent.objects.create(
            actor=user if request.user.is_authenticated and request.user.pk == user.pk else None,
            target_user=user,
            action="account.email_change_confirmed",
            entity_type="pending_email_change",
            entity_id=str(pending.pk),
            request_id=request.request_id,
        )
    messages.success(request, "Deine neue E-Mail-Adresse wurde bestätigt.")
    return redirect("accounts:profile" if request.user.is_authenticated else "accounts:login")


@login_required
def delete_account(request):
    return render(request, "accounts/delete_account.html", {"form": AccountDeleteForm()})


@login_required
@require_POST
def anonymize_account(request):
    form = AccountDeactivateForm(request.POST)
    if not form.is_valid() or not request.user.check_password(
        form.cleaned_data.get("password", "")
    ):
        if form.is_valid():
            form.add_error("password", "Das Passwort ist nicht korrekt.")
        return render(request, "accounts/delete_account.html", {"form": form}, status=400)
    anonymize_account_service(request.user, request_id=request.request_id)
    logout(request)
    return redirect("accounts:login")


@login_required
@require_POST
def permanently_delete_account(request):
    form = AccountDeleteForm(request.POST)
    if not form.is_valid() or not request.user.check_password(
        form.cleaned_data.get("password", "")
    ):
        if form.is_valid():
            form.add_error("password", "Das Passwort ist nicht korrekt.")
        return render(request, "accounts/delete_account.html", {"form": form}, status=400)
    user = request.user
    try:
        delete_account_and_data(user, request_id=request.request_id)
    except AccountDeletionFileError as exc:
        if not exc.database_deleted:
            form.add_error(None, str(exc))
            return render(
                request, "accounts/delete_account.html", {"form": form}, status=500
            )
        request.session.flush()
        return render(
            request,
            "accounts/delete_account_result.html",
            {"error": str(exc)},
            status=500,
        )
    request.session.flush()
    messages.success(request, "Dein Account und deine persönlichen Daten wurden gelöscht.")
    return redirect("accounts:login")


@login_required
def deactivate_account(request):
    return render(
        request,
        "accounts/deactivate_account.html",
        {"form": AccountDeactivateForm()},
    )


@login_required
def sessions(request):
    current = request.session.session_key
    records = list(request.user.account_sessions.all())
    for record in records:
        record.is_current = record.session_key == current
    return render(request, "accounts/sessions.html", {"sessions": records})


@login_required
@require_POST
def revoke_session_view(request, pk):
    record = request.user.account_sessions.filter(pk=pk).first()
    if not record:
        raise Http404
    if record.session_key == request.session.session_key:
        messages.error(request, "Die aktuelle Sitzung kann hier nicht beendet werden.")
    else:
        revoke_session(record)
        AuditEvent.objects.create(
            actor=request.user,
            target_user=request.user,
            action="account.session_revoked",
            request_id=request.request_id,
        )
        messages.success(request, "Sitzung beendet.")
    return redirect("accounts:sessions")


@login_required
@require_POST
def revoke_other_sessions(request):
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "Das Passwort ist nicht korrekt.")
        return redirect("accounts:sessions")
    current = request.session.session_key
    for record in list(request.user.account_sessions.exclude(session_key=current)):
        revoke_session(record)
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="account.other_sessions_revoked",
        request_id=request.request_id,
    )
    messages.success(request, "Alle anderen Sitzungen wurden beendet.")
    return redirect("accounts:sessions")
