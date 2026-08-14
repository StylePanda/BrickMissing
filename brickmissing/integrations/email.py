from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any


class EmailService:
    RESEND_ENDPOINT = "https://api.resend.com/emails"
    MODES = {"smtp", "resend", "disabled"}

    def __init__(self, config_file: Path, cipher: Any):
        self.config_file = config_file
        self.cipher = cipher

    def save(self, payload: dict[str, Any]) -> None:
        current = self._raw()
        mode = str(payload.get("mode", "smtp")).strip().lower()
        if mode not in self.MODES:
            raise ValueError("Unbekannte E-Mail-Versandart.")

        sender = str(payload.get("sender", "")).strip()
        if mode != "disabled" and not sender:
            raise ValueError("Eine Absenderadresse ist erforderlich.")
        sender_name = str(payload.get("sender_name", "")).strip()
        if any(character in sender_name for character in "\r\n<>"):
            raise ValueError("Der Absendername enthält ungültige Zeichen.")

        # Preserve the inactive provider's encrypted secret and settings so an
        # administrator can switch providers without having to enter them again.
        data: dict[str, Any] = dict(current)
        data.update(
            {
                "mode": mode,
                "sender": sender,
                "sender_name": sender_name,
                "enabled": mode != "disabled" and bool(payload.get("enabled", True)),
            }
        )
        if mode == "smtp":
            host = str(payload.get("host", "")).strip()
            if not host:
                raise ValueError("Ein SMTP-Host ist erforderlich.")
            password = str(payload.get("password", ""))
            data.update(
                {
                    "host": host,
                    "port": int(payload.get("port", 587)),
                    "username": str(payload.get("username", "")).strip(),
                    "password": (
                        self.cipher.encrypt(password)
                        if password
                        else current.get("password", "")
                    ),
                    "security": str(payload.get("security", "starttls")),
                }
            )
        elif mode == "resend":
            api_key = str(payload.get("api_key", "")).strip()
            data["api_key"] = (
                self.cipher.encrypt(api_key)
                if api_key
                else current.get("api_key", "")
            )
            if not data["api_key"]:
                raise ValueError("Ein Resend-API-Schlüssel ist erforderlich.")

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def public_config(self) -> dict[str, Any]:
        raw = self._raw()
        mode = self._mode(raw)
        configured = (
            mode == "disabled"
            or (mode == "smtp" and bool(raw.get("host") and raw.get("sender")))
            or (mode == "resend" and bool(raw.get("api_key") and raw.get("sender")))
        )
        return {
            "mode": mode,
            "configured": configured,
            "host": raw.get("host", ""),
            "port": raw.get("port", 587),
            "sender": raw.get("sender", ""),
            "sender_name": raw.get("sender_name", ""),
            "username": raw.get("username", ""),
            "security": raw.get("security", "starttls"),
            "enabled": bool(raw.get("enabled", False)),
            "password_configured": bool(raw.get("password")),
            "api_key_configured": bool(raw.get("api_key")),
        }

    def test(self, recipient: str | None = None) -> None:
        config = self._connection_config()
        target = recipient or config["sender"]
        self._send(
            target,
            "BrickMissing – E-Mail-Test erfolgreich",
            "Die E-Mail-Konfiguration von BrickMissing funktioniert.",
            config,
        )

    def send_account_created(self, recipient: str, username: str) -> bool:
        config = self._connection_config(required=False)
        if not config or not config.get("enabled"):
            return False
        self._send(
            recipient,
            "Dein BrickMissing-Konto wurde erstellt",
            (
                f"Hallo {username},\n\n"
                "dein Benutzerkonto bei BrickMissing wurde erfolgreich erstellt.\n"
                "Du kannst dich ab sofort mit deinem Benutzernamen oder deiner "
                "E-Mail-Adresse anmelden.\n\n"
                "Falls du dieses Konto nicht erwartest, wende dich bitte an den Administrator.\n\n"
                "Viele Grüße\nBrickMissing"
            ),
            config,
        )
        return True

    def send_verification(self, recipient: str, username: str, url: str) -> bool:
        return self._send_optional(
            recipient,
            "E-Mail-Adresse für BrickMissing bestätigen",
            f"Hallo {username},\n\nbestätige deine E-Mail-Adresse über diesen zeitlich begrenzten Link:\n{url}\n\nBrickMissing",
        )

    def send_password_reset(self, recipient: str, username: str, url: str) -> bool:
        return self._send_optional(
            recipient,
            "BrickMissing-Passwort zurücksetzen",
            f"Hallo {username},\n\nüber diesen einmaligen Link kannst du dein Passwort zurücksetzen:\n{url}\n\nFalls du dies nicht angefordert hast, ignoriere die Nachricht.",
        )

    def _send_optional(self, recipient: str, subject: str, body: str) -> bool:
        config = self._connection_config(required=False)
        if not config or not config.get("enabled"):
            return False
        self._send(recipient, subject, body, config)
        return True

    def _send(
        self, recipient: str, subject: str, body: str, config: dict[str, Any]
    ) -> None:
        if config["mode"] == "resend":
            self._send_resend(recipient, subject, body, config)
        else:
            self._send_smtp(recipient, subject, body, config)

    def _send_resend(
        self, recipient: str, subject: str, body: str, config: dict[str, Any]
    ) -> None:
        request = urllib.request.Request(
            self.RESEND_ENDPOINT,
            data=json.dumps(
                {
                    "from": (
                        f"{config['sender_name']} <{config['sender']}>"
                        if config.get("sender_name")
                        else config["sender"]
                    ),
                    "to": [recipient],
                    "subject": subject,
                    "text": body,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
                "User-Agent": "BrickMissing/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status not in {200, 201, 202}:
                    raise RuntimeError(
                        f"Resend hat mit HTTP {response.status} geantwortet."
                    )
        except urllib.error.HTTPError as exc:
            try:
                details = json.loads(exc.read().decode("utf-8")).get("message", "")
            except (ValueError, UnicodeDecodeError):
                details = ""
            message = f"Resend-Fehler (HTTP {exc.code})"
            raise RuntimeError(f"{message}: {details}" if details else message) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Resend ist nicht erreichbar: {exc.reason}") from exc

    @staticmethod
    def _send_smtp(
        recipient: str, subject: str, body: str, config: dict[str, Any]
    ) -> None:
        message = EmailMessage()
        message["From"] = config["sender"]
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        if config["security"] == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                config["host"], config["port"], timeout=12, context=context
            )
        else:
            client = smtplib.SMTP(config["host"], config["port"], timeout=12)
        try:
            client.ehlo()
            if config["security"] == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if config["username"]:
                client.login(config["username"], config["password"])
            client.send_message(message)
        finally:
            try:
                client.quit()
            except Exception:
                client.close()

    def _connection_config(self, required: bool = True) -> dict[str, Any] | None:
        raw = self._raw()
        mode = self._mode(raw)
        if mode == "disabled" or not raw.get("sender"):
            if required:
                raise ValueError("Der E-Mail-Versand ist deaktiviert oder nicht konfiguriert.")
            return None
        secret_name = "api_key" if mode == "resend" else "password"
        if mode == "smtp" and not raw.get("host"):
            if required:
                raise ValueError("SMTP ist noch nicht konfiguriert.")
            return None
        if mode == "resend" and not raw.get("api_key"):
            if required:
                raise ValueError("Resend ist noch nicht konfiguriert.")
            return None
        encrypted_secret = str(raw.get(secret_name, ""))
        raw[secret_name] = (
            self.cipher.decrypt(encrypted_secret) if encrypted_secret else ""
        )
        raw["mode"] = mode
        return raw

    @staticmethod
    def _mode(raw: dict[str, Any]) -> str:
        mode = str(raw.get("mode", "smtp")).lower()
        return mode if mode in EmailService.MODES else "smtp"

    def _raw(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return {}
        return json.loads(self.config_file.read_text(encoding="utf-8"))
