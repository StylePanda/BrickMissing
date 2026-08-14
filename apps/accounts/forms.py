from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError

from apps.core.client_ip import client_ip

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
