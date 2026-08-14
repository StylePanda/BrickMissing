from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.http import base36_to_int


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "brickmissing.accounts.email_verification"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{timestamp}{user.email}{user.email_verified}{user.password}"

    def check_token(self, user, token):
        if not super().check_token(user, token):
            return False
        try:
            timestamp = base36_to_int(token.split("-")[0])
        except (ValueError, IndexError):
            return False
        return (self._num_seconds(self._now()) - timestamp) <= settings.EMAIL_VERIFICATION_TIMEOUT


email_verification_token = EmailVerificationTokenGenerator()
