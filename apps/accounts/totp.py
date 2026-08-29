import base64
import hashlib
import hmac
import secrets
import struct
import time
from io import BytesIO
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet
from django.conf import settings


def _cipher():
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.TOTP_ENCRYPTION_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(secret):
    return _cipher().encrypt(secret.encode()).decode()


def decrypt_secret(value):
    return _cipher().decrypt(value.encode()).decode()


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_for(secret, timestamp=None):
    counter = int((timestamp or time.time()) // 30)
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    digest = hmac.new(base64.b32decode(padded), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str(
        (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    ).zfill(6)


def verify_code(secret, value, timestamp=None):
    if not value.isdigit() or len(value) != 6:
        return False
    now = timestamp or time.time()
    return any(
        hmac.compare_digest(code_for(secret, now + drift * 30), value) for drift in (-1, 0, 1)
    )


def provisioning_uri(secret, username):
    return f"otpauth://totp/{quote(f'BrickMissing:{username}')}?secret={secret}&issuer=BrickMissing&algorithm=SHA1&digits=6&period=30"


def qr_svg(uri, *, border=2):
    image = qrcode.make(
        uri,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=6,
        border=border,
    )
    output = BytesIO()
    image.save(output)
    return output.getvalue()
