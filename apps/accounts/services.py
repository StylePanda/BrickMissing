from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token


def send_verification_email(request, user) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    url = request.build_absolute_uri(
        reverse("accounts:verify", kwargs={"uidb64": uid, "token": token})
    )
    send_mail(
        "BrickMissing – E-Mail-Adresse bestätigen",
        f"Hallo {user.username},\n\nbitte bestätige deine E-Mail-Adresse:\n{url}\n\nDer Link ist zeitlich begrenzt.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
