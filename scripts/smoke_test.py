#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def check(url: str, expected_content: bytes | None = None) -> None:
    if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
        raise RuntimeError("smoke test only permits HTTP(S) URLs")
    request = urllib.request.Request(  # noqa: S310 - scheme allowlisted above
        url, headers={"User-Agent": "BrickMissing-Smoke/8.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = response.read(512_000)
            if response.status != 200 or (expected_content and expected_content not in body):
                raise RuntimeError(f"unexpected response from {url}: {response.status}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"smoke test failed for {url}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    check(base + "/health/", b'"database": "ok"')
    check(base + "/konto/anmelden/", b"BrickMissing")
    check(base + "/static/css/app.css", b"--brand")
    print(json.dumps({"status": "ok", "checks": ["health", "login", "static", "database"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
