from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

VERSION = "8.0.0"
ALLOWED_DIRECTORIES = (
    "apps", "config", "templates", "static", "deploy", "scripts", "requirements", "docs"
)
ALLOWED_ROOT_FILES = (
    "manage.py", "pyproject.toml", "requirements.txt", "README.md", "CHANGELOG.md"
)
FORBIDDEN_NAMES = {
    ".env", ".master.key", "smtp.json", "mariadb.json", "backups", "data",
    "cache", "var", ".venv", ".vendor", "__pycache__",
}
FORBIDDEN_TOP_LEVEL = {"backups", "data", "cache", "var", ".venv", ".vendor"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".pyo"}
SECRET_MARKERS = (
    b"BEGIN " + b"OPENSSH PRIVATE KEY",
    b"BEGIN " + b"PRIVATE KEY",
)


def _allowed_file(path: Path, source: Path) -> bool:
    relative = path.relative_to(source)
    if relative.parts[0] in FORBIDDEN_TOP_LEVEL:
        return False
    if any(part in {"__pycache__", ".venv", ".vendor"} or part.startswith(".env") for part in relative.parts):
        return False
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return False
    return path.is_file() and not path.is_symlink()


def _scan_file(path: Path) -> None:
    relative_lower = path.name.lower()
    if relative_lower in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise RuntimeError(f"Forbidden release file detected: {path.name}")
    content = path.read_bytes()
    if any(marker in content for marker in SECRET_MARKERS):
        raise RuntimeError(f"Private key material detected in: {path.name}")


def build_release(source: Path, output_root: Path) -> Path:
    source = source.resolve()
    output_root = output_root.resolve()
    destination = output_root / f"brickmissing-{VERSION}"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for directory in ALLOWED_DIRECTORIES:
        source_dir = source / directory
        if not source_dir.is_dir():
            raise RuntimeError(f"Required source directory is missing: {directory}")
        for path in source_dir.rglob("*"):
            if not _allowed_file(path, source):
                continue
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for filename in ALLOWED_ROOT_FILES:
        path = source / filename
        if not path.is_file():
            raise RuntimeError(f"Required source file is missing: {filename}")
        shutil.copy2(path, destination / filename)
    files = []
    for path in sorted(item for item in destination.rglob("*") if item.is_file()):
        _scan_file(path)
        files.append(
            {
                "path": path.relative_to(destination).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    required = [
        destination / "manage.py", destination / "static",
        destination / "deploy" / "systemd" / "brickmissing.service",
    ]
    if not all(path.exists() for path in required):
        raise RuntimeError("Release artifact is incomplete")
    if not list((destination / "apps").glob("*/migrations/*.py")):
        raise RuntimeError("Release contains no Django migrations")
    manifest = {
        "version": VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "files": files,
    }
    (destination / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8", newline="\n"
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a secret-free BrickMissing release")
    parser.add_argument("--output-root", type=Path, default=Path("dist"))
    args = parser.parse_args()
    release = build_release(Path(__file__).resolve().parents[1], args.output_root)
    print(release)


if __name__ == "__main__":
    main()
