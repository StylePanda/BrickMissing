import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class RebrickableError(ValueError):
    def __init__(self, message, code="unavailable"):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(url, headers=None, limit=5 * 1024 * 1024):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"rebrickable.com", "www.brickeconomy.com"}:
        raise ValueError("Nicht freigegebene Datenquelle")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "BrickMissing/8.0", **(headers or {})})  # noqa: S310 -- exact HTTPS host checked above
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            if int(response.headers.get("Content-Length", 0) or 0) > limit:
                raise ValueError("Antwort ist zu groß")
            payload = response.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("Antwort ist zu groß")
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise ValueError("Ungültige API-Antwort")
            return result
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ValueError("Externe API Rate Limit erreicht") from exc
        if exc.code in {401, 403}:
            raise ValueError("Externe API Authentifizierung fehlgeschlagen") from exc
        raise ValueError(f"Externe API antwortete mit HTTP {exc.code}") from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Externe Datenquelle ist nicht erreichbar oder ungültig") from exc


def normalize_rebrickable_set_number(set_number):
    number = str(set_number).strip()
    if not number or len(number) > 64 or not all(char.isalnum() or char == "-" for char in number):
        raise RebrickableError("Die Setnummer ist ungültig.", "invalid_set_number")
    return number if "-" in number else f"{number}-1"


def _rebrickable_json(path, api_key):
    if not api_key:
        raise RebrickableError("Rebrickable ist für dieses Konto nicht eingerichtet.", "missing_key")
    try:
        return fetch_json(
            "https://rebrickable.com/api/v3/lego/" + path,
            {"Authorization": f"key {api_key}"},
        )
    except ValueError as exc:
        message = str(exc)
        if "Authentifizierung" in message:
            raise RebrickableError("Der Rebrickable API-Key ist ungültig.", "authentication") from exc
        if "Rate Limit" in message:
            raise RebrickableError("Rebrickable hat zu viele Anfragen erhalten.", "rate_limit") from exc
        if "HTTP 404" in message:
            raise RebrickableError("Set wurde nicht gefunden.", "not_found") from exc
        raise RebrickableError("Rebrickable ist momentan nicht erreichbar.", "unavailable") from exc


def rebrickable_set(set_number, api_key):
    number = normalize_rebrickable_set_number(set_number)
    path = urllib.parse.quote(number, safe="")
    set_data = _rebrickable_json("sets/" + path + "/", api_key)
    parts = _rebrickable_json("sets/" + path + "/parts/?page_size=1000", api_key)
    return set_data, parts.get("results", [])


def _rebrickable_get(path, api_key):
    return _rebrickable_json(path, api_key)


def rebrickable_minifigures(set_number, api_key):
    number = normalize_rebrickable_set_number(set_number)
    figures = _rebrickable_get(
        "sets/" + urllib.parse.quote(number, safe="") + "/minifigs/?page_size=1000", api_key
    ).get("results", [])
    result = []
    for figure in figures:
        figure_number = str(figure.get("set_num") or "")
        if not figure_number:
            continue
        parts = _rebrickable_get(
            "minifigs/" + urllib.parse.quote(figure_number, safe="") + "/parts/?page_size=1000", api_key
        ).get("results", [])
        result.append((figure, parts))
    return result


def rebrickable_instructions(set_number, api_key):
    number = normalize_rebrickable_set_number(set_number)
    fallback = [
        {
            "name": "Rebrickable",
            "url": "https://rebrickable.com/instructions/" + urllib.parse.quote(number, safe=""),
            "source": "Rebrickable",
        },
        {
            "name": "LEGO Bauanleitungen",
            "url": "https://www.lego.com/de-de/service/buildinginstructions/" + urllib.parse.quote(number.split("-")[0], safe=""),
            "source": "LEGO",
        },
    ]
    try:
        rows = _rebrickable_get(
            "sets/" + urllib.parse.quote(number, safe="") + "/instructions/", api_key
        ).get("results", [])
    except ValueError:
        return fallback
    instructions = []
    for row in rows:
        url = row.get("url") or row.get("pdf_url")
        if isinstance(url, str) and url.startswith("https://"):
            instructions.append(
                {"name": row.get("name") or "Bauanleitung", "url": url, "source": "Rebrickable"}
            )
    return instructions or fallback


def test_rebrickable_connection(api_key):
    return _rebrickable_json("colors/?page_size=1", api_key)


def rebrickable_set_metadata(set_number, api_key):
    number = normalize_rebrickable_set_number(set_number)
    encoded = urllib.parse.quote(number, safe="")
    metadata = _rebrickable_json(f"sets/{encoded}/", api_key)
    theme_name = subtheme_name = ""
    theme_id = metadata.get("theme_id")
    if theme_id is not None:
        current_theme = _rebrickable_json(f"themes/{int(theme_id)}/", api_key)
        theme_name = str(current_theme.get("name") or "")
        parent_id = current_theme.get("parent_id")
        if parent_id is not None:
            subtheme_name = theme_name
            parent = _rebrickable_json(f"themes/{int(parent_id)}/", api_key)
            theme_name = str(parent.get("name") or theme_name)
    figures = _rebrickable_json(f"sets/{encoded}/minifigs/?page_size=1", api_key)
    return {
        "set_number": str(metadata.get("set_num") or number),
        "name": str(metadata.get("name") or ""),
        "year": metadata.get("year"),
        "theme": theme_name,
        "subtheme": subtheme_name,
        "total_parts": metadata.get("num_parts"),
        "minifigures": figures.get("count", 0),
        "image_url": str(metadata.get("set_img_url") or ""),
    }


def brickeconomy_set(set_number):
    if not settings.BRICKECONOMY_API_KEY:
        raise ValueError("BRICKECONOMY_API_KEY ist nicht konfiguriert")
    number = set_number if "-" in set_number else f"{set_number}-1"
    payload = fetch_json("https://www.brickeconomy.com/api/v1/set/" + urllib.parse.quote(number, safe="") + "?currency=EUR", {"x-apikey": settings.BRICKECONOMY_API_KEY})
    data = payload.get("data") or {}
    if not data:
        raise ValueError("Keine Preisdaten gefunden")
    return data


def brickset_set(set_number):
    if not settings.BRICKSET_API_KEY:
        raise ValueError("BRICKSET_API_KEY ist nicht konfiguriert")
    number = set_number if "-" in set_number else f"{set_number}-1"
    query = urllib.parse.urlencode({
        "apiKey": settings.BRICKSET_API_KEY,
        "userHash": "",
        "params": json.dumps({"setNumber": number}, separators=(",", ":")),
    })
    payload = _external_json("https://brickset.com/api/v3.asmx/getSets?" + query)
    rows = payload.get("sets") or []
    if payload.get("status") != "success" or not rows:
        raise ValueError(payload.get("message") or "Keine Brickset-Daten gefunden")
    return rows[0]


def lego_pick_a_brick_url(part_number):
    number = str(part_number).strip()
    if not number:
        raise ValueError("Teilenummer fehlt")
    return "https://www.lego.com/de-at/pick-and-build/pick-a-brick?" + urllib.parse.urlencode(
        {"query": number, "includeOutOfStock": "true"}
    )


def _oauth_escape(value):
    return urllib.parse.quote(str(value), safe="~-._")


def bricklink_price(item_type, number, condition="U"):
    credentials = {
        "oauth_consumer_key": settings.BRICKLINK_CONSUMER_KEY,
        "consumer_secret": settings.BRICKLINK_CONSUMER_SECRET,
        "oauth_token": settings.BRICKLINK_TOKEN,
        "token_secret": settings.BRICKLINK_TOKEN_SECRET,
    }
    if not all(credentials.values()):
        raise ValueError("BrickLink OAuth ist nicht konfiguriert")
    base_url = (
        "https://api.bricklink.com/api/store/v1/items/"
        + urllib.parse.quote(str(item_type).upper(), safe="") + "/"
        + urllib.parse.quote(str(number), safe="") + "/price"
    )
    query = {"guide_type": "sold", "new_or_used": condition, "currency_code": "EUR", "vat": "Y"}
    oauth = {
        "oauth_consumer_key": credentials["oauth_consumer_key"],
        "oauth_nonce": secrets.token_hex(16), "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())), "oauth_token": credentials["oauth_token"],
        "oauth_version": "1.0",
    }
    normalized = "&".join(
        f"{_oauth_escape(key)}={_oauth_escape(value)}"
        for key, value in sorted({**query, **oauth}.items())
    )
    base_string = "&".join(("GET", _oauth_escape(base_url), _oauth_escape(normalized)))
    signing_key = _oauth_escape(credentials["consumer_secret"]) + "&" + _oauth_escape(credentials["token_secret"])
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode("ascii")
    authorization = "OAuth " + ", ".join(
        f'{_oauth_escape(key)}="{_oauth_escape(value)}"' for key, value in sorted(oauth.items())
    )
    payload = _external_json(
        base_url + "?" + urllib.parse.urlencode(query),
        {"Authorization": authorization},
    )
    data = payload.get("data") or {}
    if not data:
        raise ValueError("Keine BrickLink-Preisdaten gefunden")
    return data


def _external_json(url, headers=None, limit=5 * 1024 * 1024):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"brickset.com", "api.bricklink.com"}:
        raise ValueError("Nicht freigegebene Datenquelle")
    request = urllib.request.Request(  # noqa: S310 -- exact HTTPS hosts checked above
        url, headers={"Accept": "application/json", "User-Agent": "BrickMissing/8.0", **(headers or {})}
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            payload = response.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("Antwort ist zu groß")
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise ValueError("Ungültige API-Antwort")
            return result
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ValueError("Externe API Rate Limit erreicht") from exc
        if exc.code in {401, 403}:
            raise ValueError("Externe API Authentifizierung fehlgeschlagen") from exc
        raise ValueError(f"Externe API antwortete mit HTTP {exc.code}") from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Externe API ist nicht erreichbar oder ungültig") from exc


def validated_image_url(raw_url):
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Nur HTTPS-Bildadressen sind erlaubt")
    host = parsed.hostname.casefold()
    if not any(host == allowed or host.endswith("." + allowed) for allowed in settings.IMAGE_PROXY_ALLOWED_HOSTS):
        raise ValueError("Bildhost ist nicht freigegeben")
    for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(result[4][0])
        if not address.is_global or str(address) in {"100.100.100.200"}:
            raise ValueError("Private oder lokale Zieladresse ist nicht erlaubt")
    return raw_url


def fetch_image(raw_url, limit=5 * 1024 * 1024):
    url = validated_image_url(raw_url)
    request = urllib.request.Request(url, headers={"Accept": "image/png,image/jpeg,image/webp", "User-Agent": "BrickMissing/8.0"})  # noqa: S310 -- scheme, host and resolved IP validated above
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("Antwort ist kein unterstütztes Bild")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Bild ist zu groß")
        return data, content_type
