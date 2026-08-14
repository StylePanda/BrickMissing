from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

FORBIDDEN_PARTS = {".env", ".git", ".master.key", ".pytest_cache", ".ruff_cache", ".vendor", ".venv", "__pycache__", "node_modules"}
FORBIDDEN_TOP_LEVEL = {"backups", "cache", "data", "var"}
FORBIDDEN_NAMES = {"mariadb.json", "smtp.json"}
FORBIDDEN_SUFFIXES = {".db", ".log", ".pyc", ".pyo", ".sqlite", ".sqlite3"}
ALLOWED_DIRECTORIES = {"apps", "config", "deploy", "docs", "requirements", "scripts", "static", "templates"}
ALLOWED_ROOT_FILES = {"CHANGELOG.md", "README.md", "manage.py", "pyproject.toml", "requirements.txt"}
SECRET_MARKERS = (
    b"BEGIN " + b"OPENSSH PRIVATE KEY",
    b"BEGIN " + b"PRIVATE KEY",
)


class ReleaseVerificationError(RuntimeError):
    pass


def _safe_manifest_path(raw: object) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ReleaseVerificationError("Manifest contains an invalid path")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ReleaseVerificationError("Manifest contains an unsafe path")
    return path


def verify_release(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    manifest_path = root / "RELEASE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError("Release manifest is missing or invalid") from exc
    if manifest.get("version") != "8.0.0" or not isinstance(manifest.get("built_at"), str):
        raise ReleaseVerificationError("Release manifest metadata is invalid")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ReleaseVerificationError("Release manifest contains no files")
    declared: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReleaseVerificationError("Release manifest entry is invalid")
        relative = _safe_manifest_path(entry.get("path"))
        key = relative.as_posix()
        if key in declared:
            raise ReleaseVerificationError("Release manifest contains duplicate paths")
        declared.add(key)
        if relative.parts[0].lower() in FORBIDDEN_TOP_LEVEL or any(
            part.lower() in FORBIDDEN_PARTS or part.lower().startswith(".env")
            for part in relative.parts
        ):
            raise ReleaseVerificationError("Release contains a forbidden path")
        if (
            (len(relative.parts) == 1 and relative.name not in ALLOWED_ROOT_FILES)
            or (len(relative.parts) > 1 and relative.parts[0] not in ALLOWED_DIRECTORIES)
        ):
            raise ReleaseVerificationError("Release path is outside the allowlist")
        if relative.name.lower() in FORBIDDEN_NAMES or relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ReleaseVerificationError("Release contains a forbidden file")
        target = root.joinpath(*relative.parts)
        if not target.is_file() or target.is_symlink():
            raise ReleaseVerificationError("Release file is missing or is a symlink")
        if not isinstance(entry.get("size"), int) or target.stat().st_size != entry["size"]:
            raise ReleaseVerificationError("Release file size mismatch")
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ReleaseVerificationError("Release hash metadata is invalid")
        content = target.read_bytes()
        if any(marker in content for marker in SECRET_MARKERS):
            raise ReleaseVerificationError("Release contains private key material")
        if hashlib.sha256(content).hexdigest() != expected_hash.lower():
            raise ReleaseVerificationError("Release file hash mismatch")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path != manifest_path}
    if actual != declared:
        raise ReleaseVerificationError("Release contains missing or undeclared files")
    return {"version": manifest["version"], "files": len(declared)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a BrickMissing release artifact")
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    result = verify_release(args.artifact)
    print(f"Verified BrickMissing {result['version']}: {result['files']} files")


if __name__ == "__main__":
    main()
