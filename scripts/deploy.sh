#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: deploy.sh /absolute/path/to/brickmissing-8.0.0" >&2
  exit 2
fi

ARTIFACT=$1
ROOT=${BRICKMISSING_ROOT:-/var/www/brickmissing}
RELEASES="$ROOT/releases"
SHARED="$ROOT/shared"
CURRENT="$ROOT/current"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RELEASE="$RELEASES/8.0.0-$STAMP-$$"
PREVIOUS=""

case "$ARTIFACT" in /*) ;; *) echo "Artifact path must be absolute" >&2; exit 2 ;; esac
test -d "$ARTIFACT"
test -f "$ARTIFACT/RELEASE_MANIFEST.json"
test -f "$ARTIFACT/manage.py"
python3 "$ARTIFACT/scripts/verify_release.py" "$ARTIFACT"

mkdir -p "$RELEASES" "$SHARED/var"
cp -a "$ARTIFACT/." "$RELEASE/"
python3 "$RELEASE/scripts/verify_release.py" "$RELEASE"
rm -rf "$RELEASE/var"
ln -s "$SHARED/var" "$RELEASE/var"

if [ -L "$CURRENT" ]; then
  PREVIOUS=$(readlink -f "$CURRENT")
fi

cleanup_failed_release() {
  if [ ! -L "$CURRENT" ] || [ "$(readlink -f "$CURRENT" 2>/dev/null || true)" != "$RELEASE" ]; then
    rm -rf "$RELEASE"
  fi
}
trap cleanup_failed_release EXIT INT TERM

cd "$RELEASE"
python3 -m venv .venv
.venv/bin/pip install --requirement requirements/production.txt
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --plan
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy

python3 scripts/release_switch.py "$ROOT" "$RELEASE" --temporary-name ".current-$STAMP-$$"
sudo systemctl restart brickmissing

if ! .venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8000; then
  if [ -n "$PREVIOUS" ] && [ -d "$PREVIOUS" ]; then
    python3 scripts/release_switch.py "$ROOT" "$PREVIOUS" --temporary-name ".rollback-$STAMP-$$"
    sudo systemctl restart brickmissing
    "$PREVIOUS/.venv/bin/python" "$PREVIOUS/scripts/smoke_test.py" --base-url http://127.0.0.1:8000
  fi
  echo "Deployment smoke test failed; previous release restored" >&2
  exit 1
fi

trap - EXIT INT TERM
printf '%s\n' "Deployment activated: $RELEASE"
