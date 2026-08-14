from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import struct
import time
import urllib.parse
from datetime import timedelta
from typing import Any

from brickmissing.core.time import utc_now


class AccountSecurityService:
    def __init__(self, cipher: Any):
        self.cipher = cipher

    def issue_token(
        self, conn: sqlite3.Connection, user_id: int, purpose: str, minutes: int
    ) -> str:
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        conn.execute(
            "DELETE FROM account_tokens WHERE user_id=? AND purpose=? AND used_at IS NULL",
            (user_id, purpose),
        )
        conn.execute(
            """INSERT INTO account_tokens(user_id,purpose,token_hash,expires_at)
               VALUES(?,?,?,?)""",
            (user_id, purpose, digest, (utc_now() + timedelta(minutes=minutes)).isoformat()),
        )
        return token

    def consume_token(
        self, conn: sqlite3.Connection, token: str, purpose: str
    ) -> int:
        digest = hashlib.sha256(str(token).encode("ascii")).hexdigest()
        row = conn.execute(
            """SELECT id,user_id FROM account_tokens
               WHERE token_hash=? AND purpose=? AND used_at IS NULL AND expires_at>?
               LIMIT 1""",
            (digest, purpose, utc_now().isoformat()),
        ).fetchone()
        if not row:
            raise ValueError("Der Link ist ungültig oder abgelaufen.")
        conn.execute(
            "UPDATE account_tokens SET used_at=? WHERE id=?",
            (utc_now().isoformat(), row["id"]),
        )
        return int(row["user_id"])

    @staticmethod
    def new_totp_secret() -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

    @staticmethod
    def provisioning_uri(secret: str, username: str) -> str:
        label = urllib.parse.quote(f"BrickMissing:{username}")
        return (
            f"otpauth://totp/{label}?secret={secret}"
            "&issuer=BrickMissing&algorithm=SHA1&digits=6&period=30"
        )

    @staticmethod
    def verify_totp(secret: str, code: str, now: int | None = None) -> bool:
        clean = str(code).replace(" ", "")
        if not clean.isdigit() or len(clean) != 6:
            return False
        timestamp = int(now if now is not None else time.time())
        padded = secret + "=" * ((8 - len(secret) % 8) % 8)
        key = base64.b32decode(padded, casefold=True)
        for offset in (-1, 0, 1):
            counter = timestamp // 30 + offset
            digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
            index = digest[-1] & 0x0F
            value = (struct.unpack(">I", digest[index : index + 4])[0] & 0x7FFFFFFF) % 1_000_000
            if hmac.compare_digest(f"{value:06d}", clean):
                return True
        return False
