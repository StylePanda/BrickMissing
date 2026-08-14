from __future__ import annotations

import argparse
import os
from pathlib import Path


def _contained_release(root: Path, release: Path) -> Path:
    releases = (root.resolve() / "releases").resolve()
    release = release.resolve(strict=True)
    if release.parent != releases or not release.is_dir():
        raise ValueError("Release must be a direct child of the releases directory")
    return release


def switch_release(root: Path, release: Path, *, temporary_name: str) -> None:
    root = root.resolve()
    release = _contained_release(root, release)
    current = root / "current"
    temporary = root / temporary_name
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError("Temporary activation link already exists")
    os.symlink(release, temporary, target_is_directory=True)
    try:
        os.replace(temporary, current)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Atomically switch BrickMissing current")
    parser.add_argument("root", type=Path)
    parser.add_argument("release", type=Path)
    parser.add_argument("--temporary-name", required=True)
    args = parser.parse_args()
    switch_release(args.root, args.release, temporary_name=args.temporary_name)


if __name__ == "__main__":
    main()
