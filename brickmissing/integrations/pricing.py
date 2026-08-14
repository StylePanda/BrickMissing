from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class PricingService:
    """Price integrations, including free LEGO and Brickset sources."""

    def __init__(self, path: Path, cipher: Any):
        self.path = path
        self.cipher = cipher

    def _load(self) -> dict[str, Any]:
        defaults = {
            "brickset_api_key": "",
            "brickeconomy_api_key": "",
            "bricklink_consumer_key": "",
            "bricklink_consumer_secret": "",
            "bricklink_token": "",
            "bricklink_token_secret": "",
        }
        if self.path.exists():
            try:
                defaults.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        for key in tuple(defaults):
            value = str(defaults[key] or "")
            defaults[key] = self.cipher.decrypt(value) if value else ""
        return defaults

    def public_config(self) -> dict[str, bool]:
        data = self._load()
        return {
            "brickset_configured": bool(data["brickset_api_key"]),
            "lego_pick_a_brick": True,
            "brickeconomy_configured": bool(data["brickeconomy_api_key"]),
            "bricklink_configured": all(
                data[key] for key in (
                    "bricklink_consumer_key", "bricklink_consumer_secret",
                    "bricklink_token", "bricklink_token_secret",
                )
            ),
        }

    def save(self, payload: dict[str, Any]) -> dict[str, bool]:
        current = self._load()
        for key in tuple(current):
            if key in payload and str(payload[key]).strip():
                current[key] = str(payload[key]).strip()
            if payload.get(f"clear_{key}"):
                current[key] = ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = {
            key: self.cipher.encrypt(value) if value else ""
            for key, value in current.items()
        }
        self.path.write_text(
            json.dumps(encrypted, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.public_config()

    @staticmethod
    def _json(request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", "replace")
            raise ValueError(f"Preisquelle antwortete mit HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"Preisquelle ist nicht erreichbar: {exc.reason}") from exc

    def brickeconomy_set(self, set_number: str) -> dict[str, Any]:
        key = self._load()["brickeconomy_api_key"]
        if not key:
            raise ValueError("BrickEconomy-API-Schlüssel fehlt.")
        number = set_number if "-" in set_number else f"{set_number}-1"
        url = (
            "https://www.brickeconomy.com/api/v1/set/"
            + urllib.parse.quote(number)
            + "?currency=EUR"
        )
        payload = self._json(urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "BrickMissing-Pro/7.0",
                "x-apikey": key,
            },
        ))
        data = payload.get("data") or {}
        if not data:
            raise ValueError(f"BrickEconomy kennt Set {number} nicht.")
        return data

    def brickset_set(self, set_number: str) -> dict[str, Any]:
        key = self._load()["brickset_api_key"]
        if not key:
            raise ValueError("Der kostenlose Brickset-API-Schlüssel fehlt.")
        number = set_number if "-" in set_number else f"{set_number}-1"
        query = urllib.parse.urlencode({
            "apiKey": key,
            "userHash": "",
            "params": json.dumps({"setNumber": number}, separators=(",", ":")),
        })
        payload = self._json(urllib.request.Request(
            "https://brickset.com/api/v3.asmx/getSets?" + query,
            headers={"Accept": "application/json", "User-Agent": "BrickMissing-Pro/7.0"},
        ))
        sets = payload.get("sets") or []
        if payload.get("status") != "success" or not sets:
            raise ValueError(payload.get("message") or f"Brickset kennt Set {number} nicht.")
        return sets[0]

    @staticmethod
    def _lego_products(page: str) -> list[dict[str, Any]]:
        for raw in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                value = json.loads(html.unescape(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if value.get("@type") == "ItemList":
                return [
                    item for item in value.get("itemListElement", [])
                    if isinstance(item, dict) and item.get("@type") == "Product"
                ]
        return []

    def lego_pick_a_brick(self, numbers: list[str]) -> dict[str, dict[str, Any]]:
        clean = list(dict.fromkeys(
            str(number).strip() for number in numbers if str(number).strip()
        ))
        if not clean:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(clean), 20):
            batch = clean[offset:offset + 20]
            url = (
                "https://www.lego.com/de-at/pick-and-build/pick-a-brick?"
                + urllib.parse.urlencode({
                    "query": " ".join(batch),
                    "perPage": 200,
                    "includeOutOfStock": "true",
                })
            )
            request = urllib.request.Request(url, headers={
                "Accept": "text/html",
                "Accept-Language": "de-AT,de;q=0.9",
                "User-Agent": "Mozilla/5.0 BrickMissing-Pro/7.0",
            })
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    page = response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                raise ValueError(f"LEGO Pick a Brick antwortete mit HTTP {exc.code}.") from exc
            except urllib.error.URLError as exc:
                raise ValueError(f"LEGO Pick a Brick ist nicht erreichbar: {exc.reason}") from exc
            for product in self._lego_products(page):
                offer = product.get("offers") or {}
                sku = str(product.get("sku") or "").strip()
                price = float(offer.get("price") or 0)
                if sku and price > 0:
                    result[sku] = {
                        "price": price,
                        "currency": offer.get("priceCurrency") or "EUR",
                        "name": product.get("name") or "",
                        "available": str(offer.get("availability") or "").endswith("/InStock"),
                    }
        return result

    @staticmethod
    def _escape(value: Any) -> str:
        return urllib.parse.quote(str(value), safe="~-._")

    def bricklink_price(
        self, item_type: str, number: str, *, condition: str = "U"
    ) -> dict[str, Any]:
        config = self._load()
        required = (
            "bricklink_consumer_key", "bricklink_consumer_secret",
            "bricklink_token", "bricklink_token_secret",
        )
        if not all(config[key] for key in required):
            raise ValueError("BrickLink-OAuth-Zugangsdaten fehlen.")
        base_url = (
            "https://api.bricklink.com/api/store/v1/items/"
            + urllib.parse.quote(item_type.upper())
            + "/"
            + urllib.parse.quote(number, safe="")
            + "/price"
        )
        query = {
            "guide_type": "sold",
            "new_or_used": condition,
            "currency_code": "EUR",
            "vat": "Y",
        }
        oauth = {
            "oauth_consumer_key": config["bricklink_consumer_key"],
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": config["bricklink_token"],
            "oauth_version": "1.0",
        }
        signature_values = sorted({**query, **oauth}.items())
        normalized = "&".join(
            f"{self._escape(key)}={self._escape(value)}"
            for key, value in signature_values
        )
        base_string = "&".join((
            "GET", self._escape(base_url), self._escape(normalized)
        ))
        signing_key = (
            self._escape(config["bricklink_consumer_secret"])
            + "&"
            + self._escape(config["bricklink_token_secret"])
        )
        oauth["oauth_signature"] = base64.b64encode(
            hmac.new(
                signing_key.encode("utf-8"),
                base_string.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("ascii")
        authorization = "OAuth " + ", ".join(
            f'{self._escape(key)}="{self._escape(value)}"'
            for key, value in sorted(oauth.items())
        )
        payload = self._json(urllib.request.Request(
            base_url + "?" + urllib.parse.urlencode(query),
            headers={
                "Accept": "application/json",
                "Authorization": authorization,
                "User-Agent": "BrickMissing-Pro/7.0",
            },
        ))
        data = payload.get("data") or {}
        if not data:
            raise ValueError(f"BrickLink kennt {item_type} {number} nicht.")
        return data
