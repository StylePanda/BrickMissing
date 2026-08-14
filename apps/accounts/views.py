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

from .forms import EmailChangeForm, RegistrationForm, VerifiedAuthenticationForm
from .models import RecoveryCode, User
from .services import send_verification_email
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
    user = request.user if request.user.is_authenticated else User.objects.filter(email__iexact=email, is_active=True).first()
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
                actor=request.user, target_user=request.user,
                action="account.email_changed", request_id=request.request_id,
            )
            messages.success(request, "E-Mail geändert. Bitte erneut bestätigen.")
            return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


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
                    actor=user, target_user=user, action="account.recovery_code_used",
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
    email_template_name = "accounts/password_reset_email.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST" and limited(request, "password-reset", 5, 3600):
            return HttpResponse("Zu viele Anfragen. Bitte später erneut versuchen.", status=429)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        AuditEvent.objects.create(
            action="account.password_reset_requested",
            remote_address=client_ip(self.request), request_id=self.request.request_id,
        )
        return super().form_valid(form)


class AuditedPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        AuditEvent.objects.create(
            target_user=self.user, action="account.password_reset_completed",
            remote_address=client_ip(self.request), request_id=self.request.request_id,
        )
        return response


class AuditedPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change_form.html"
    success_url = "/konto/profil/"

    def form_valid(self, form):
        response = super().form_valid(form)
        AuditEvent.objects.create(
            actor=self.request.user, target_user=self.request.user,
            action="account.password_changed", request_id=self.request.request_id,
        )
        return response
