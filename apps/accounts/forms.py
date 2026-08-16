from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError

from apps.core.client_ip import client_ip
from apps.core.email import public_base_url

from .models import User


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="E-Mail")

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).casefold()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Für diese E-Mail-Adresse besteht bereits ein Konto.")
        return email

    def clean_password2(self):
        password = self.cleaned_data.get("password2", "")
        if password != self.cleaned_data.get("password1"):
            raise ValidationError("Die beiden Passwörter stimmen nicht überein.")
        if len(password) > 128:
            raise ValidationError("Das Passwort darf höchstens 128 Zeichen lang sein.")
        validate_password(password, self.instance)
        return password


class EmailChangeForm(forms.Form):
    email = forms.EmailField(label="Neue E-Mail-Adresse")
    password = forms.CharField(label="Aktuelles Passwort", widget=forms.PasswordInput)


class RebrickableApiKeyForm(forms.Form):
    api_key = forms.CharField(
        label="Rebrickable API-Key",
        max_length=255,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}, render_value=False),
    )

    def clean_email(self):
        return User.objects.normalize_email(self.cleaned_data["email"]).casefold()


class AccountDeactivateForm(forms.Form):
    password = forms.CharField(label="Aktuelles Passwort", widget=forms.PasswordInput)
    confirmation = forms.CharField(label="Zur Bestätigung „DEAKTIVIEREN“ eingeben")

    def clean_confirmation(self):
        value = self.cleaned_data["confirmation"].strip().upper()
        if value != "DEAKTIVIEREN":
            raise ValidationError("Bitte gib zur Bestätigung „DEAKTIVIEREN“ ein.")
        return value


class AccountDeleteForm(forms.Form):
    password = forms.CharField(label="Aktuelles Passwort", widget=forms.PasswordInput)
    confirmation = forms.CharField(label="Zur Bestätigung „ACCOUNT LÖSCHEN“ eingeben")

    def clean_confirmation(self):
        value = " ".join(self.cleaned_data["confirmation"].strip().upper().split())
        if value != "ACCOUNT LÖSCHEN":
            raise ValidationError("Bitte gib zur Bestätigung „ACCOUNT LÖSCHEN“ ein.")
        return value


class PersonalDataExportForm(forms.Form):
    password = forms.CharField(
        label="Aktuelles Passwort",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    confirmation = forms.CharField(label="Zur Bestätigung „EXPORTIEREN“ eingeben")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["password"].required = user.has_usable_password()
        if not user.has_usable_password():
            self.fields["password"].help_text = (
                "Für dieses Konto ist kein verwendbares Passwort hinterlegt. "
                "Die bestätigte aktive Anmeldung und das Bestätigungswort werden verwendet."
            )

    def clean_confirmation(self):
        value = self.cleaned_data["confirmation"].strip().upper()
        if value != "EXPORTIEREN":
            raise ValidationError("Bitte gib zur Bestätigung „EXPORTIEREN“ ein.")
        return value

    def clean(self):
        cleaned = super().clean()
        if self.user.has_usable_password() and not self.user.check_password(
            cleaned.get("password", "")
        ):
            self.add_error("password", "Das Passwort ist nicht korrekt.")
        return cleaned


class DeliverablePasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        for user in super().get_users(email):
            if not user.has_placeholder_email and user.email_verified:
                yield user

    def save(self, *args, **kwargs):
        request = kwargs.get("request")
        base_url = public_base_url(request)
        scheme, domain = base_url.split("://", 1)
        kwargs["domain_override"] = domain
        kwargs["use_https"] = scheme == "https"
        extra_context = dict(kwargs.get("extra_email_context") or {})
        extra_context.update(
            {
                "public_url": base_url,
                "privacy_url": f"{base_url}/datenschutz/",
                "imprint_url": f"{base_url}/impressum/",
                "expiry_seconds": settings.PASSWORD_RESET_TIMEOUT,
            }
        )
        kwargs["extra_email_context"] = extra_context
        return super().save(*args, **kwargs)


class VerifiedAuthenticationForm(AuthenticationForm):
    def clean(self):
        key = f"rate:login:{client_ip(self.request)}"
        try:
            attempts = cache.incr(key)
        except ValueError:
            cache.set(key, 1, 300)
            attempts = 1
        if attempts > 10:
            raise ValidationError("Zu viele Anmeldeversuche. Bitte später erneut versuchen.")
        cleaned = super().clean()
        if self.user_cache and not self.user_cache.email_verified:
            raise ValidationError("Bitte bestätige zuerst deine E-Mail-Adresse.")
        if self.user_cache:
            cache.delete(key)
        return cleaned
