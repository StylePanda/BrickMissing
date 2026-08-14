from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

IMAGE_HOSTS = frozenset({
    "cdn.rebrickable.com", "rebrickable.com", "www.rebrickable.com",
    "www.lego.com", "images.brickset.com",
})
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


def normalize_image_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if len(url) > 2_000:
        raise ValueError("Bild-URL ist zu lang.")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Bild-URL muss mit http:// oder https:// beginnen.")
    return url


class AssetService:
    """Trusted image cache and local QR generation, independent of HTTP routing."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir

    def cached_image(self, url: str) -> tuple[bytes, str]:
        normalized = normalize_image_url(url)
        parsed = urllib.parse.urlparse(normalized)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in IMAGE_HOSTS:
            raise ValueError("Diese Bildquelle ist nicht freigegeben.")
        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        folder = self.cache_dir / "images"
        folder.mkdir(parents=True, exist_ok=True)
        data_path, meta_path = folder / f"{key}.bin", folder / f"{key}.json"
        if data_path.exists() and meta_path.exists():
            try:
                content_type = str(json.loads(meta_path.read_text(encoding="utf-8")).get("content_type", ""))
                data = data_path.read_bytes()
                if content_type in IMAGE_TYPES and 0 < len(data) <= 8_000_000:
                    return data, content_type
            except (OSError, ValueError, json.JSONDecodeError):
                data_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
        request = urllib.request.Request(normalized, headers={
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif;q=0.8",
            "User-Agent": "Mozilla/5.0 BrickMissing-Pro/7.0",
            "Referer": f"{parsed.scheme}://{parsed.netloc}/",
        })
        last_error: Exception | None = None
        for _ in range(2):
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    content_type = response.headers.get_content_type().lower()
                    if content_type not in IMAGE_TYPES:
                        raise ValueError("Die Bildquelle lieferte keine unterstützte Bilddatei.")
                    data = response.read(8_000_001)
                    if not data or len(data) > 8_000_000:
                        raise ValueError("Das Bild ist leer oder größer als 8 MB.")
                    temp_data, temp_meta = data_path.with_suffix(".bin.tmp"), meta_path.with_suffix(".json.tmp")
                    temp_data.write_bytes(data)
                    temp_meta.write_text(json.dumps({"url": normalized, "content_type": content_type}), encoding="utf-8")
                    temp_data.replace(data_path)
                    temp_meta.replace(meta_path)
                    return data, content_type
            except (OSError, ValueError, urllib.error.URLError) as exc:
                last_error = exc
        raise ValueError(f"Bild konnte nicht geladen werden: {last_error}")

    @staticmethod
    def qr_svg(text: str) -> bytes:
        import qrcode
        import qrcode.image.svg
        target = str(text or "").strip()
        if not target:
            raise ValueError("Für den QR-Code fehlt ein Ziel.")
        if len(target) > 2_048:
            raise ValueError("Das QR-Code-Ziel ist zu lang.")
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        qr.add_data(target)
        qr.make(fit=True)
        output = io.BytesIO()
        qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(output)
        return output.getvalue()


class StaticAssetController:
    """Resolves public static routes without coupling them to the API handler."""

    def __init__(self, project_root: Path, frontend_dir: Path):
        self.routes = {
            "/": (frontend_dir / "index.html", "text/html; charset=utf-8"),
            "/app.css": (project_root / "app.css", "text/css; charset=utf-8"),
            "/core.js": (frontend_dir / "core.js", "text/javascript; charset=utf-8"),
            "/app.js": (frontend_dir / "app.js", "text/javascript; charset=utf-8"),
            "/advanced-features.css": (frontend_dir / "advanced-features.css", "text/css; charset=utf-8"),
            "/advanced-features.js": (frontend_dir / "advanced-features.js", "text/javascript; charset=utf-8"),
            "/pro7.js": (frontend_dir / "pro7.js", "text/javascript; charset=utf-8"),
            "/manifest.webmanifest": (frontend_dir / "manifest.webmanifest", "application/manifest+json; charset=utf-8"),
            "/service-worker.js": (frontend_dir / "service-worker.js", "text/javascript; charset=utf-8"),
            "/offline.html": (frontend_dir / "offline.html", "text/html; charset=utf-8"),
            "/offline.js": (frontend_dir / "offline.js", "text/javascript; charset=utf-8"),
        }

    def resolve(self, path: str) -> tuple[Path, str] | None:
        return self.routes.get(path)
