import base64
import hashlib

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare


class LegacyBrickMissingPBKDF2Hasher(BasePasswordHasher):
    """Verifier for v7's pbkdf2_sha256$iterations$salt$digest format."""

    algorithm = "brickmissing_pbkdf2_sha256"

    def encode(self, password, salt, iterations=310_000):
        self._check_encode_args(password, salt)
        salt_bytes = base64.b64decode(salt)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, iterations)
        return f"{self.algorithm}${iterations}${salt}${base64.b64encode(digest).decode()}"

    def verify(self, password, encoded):
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        if algorithm not in {self.algorithm, "pbkdf2_sha256"}:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(iterations)
        )
        return constant_time_compare(base64.b64encode(candidate).decode(), digest)

    def safe_summary(self, encoded):
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        return {
            "algorithm": algorithm,
            "iterations": iterations,
            "salt": mask_hash(salt),
            "hash": mask_hash(digest),
        }

    def harden_runtime(self, password, encoded):
        return None
