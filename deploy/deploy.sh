#!/usr/bin/env bash
# Build here, ship one release to the server, switch to it, check it answers.
#
#   bash deploy/deploy.sh            deploy the commit that is checked out
#   bash deploy/deploy.sh rollback   switch back to the release before the current one
#
# Needs: ssh access to the server, Node with corepack for the web build.
set -euo pipefail

HOST="${AVALON_HOST:-ubuntu@119.28.31.238}"
KEY="${AVALON_KEY:-$HOME/.ssh/sleep0.pem}"
SSH=(ssh -i "$KEY" -o BatchMode=yes "$HOST")

cd "$(dirname "$0")/.."

if [[ "${1:-}" == "rollback" ]]; then
  "${SSH[@]}" "sudo bash /opt/avalon/app/deploy/remote.sh rollback"
  exit 0
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Commit or stash your changes first: a release is one commit." >&2
  exit 1
fi
REV="$(git rev-parse --short HEAD)"

echo "== building the web app ($REV)"
(cd apps/web && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm install --frozen-lockfile >/dev/null \
  && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm build >/dev/null)

BUNDLE="$(mktemp -d)/avalon-$REV.tgz"
tar -czf "$BUNDLE" \
  apps/api/app apps/api/migrations apps/api/alembic.ini apps/api/pyproject.toml \
  apps/web/dist deploy

echo "== uploading"
scp -i "$KEY" -o BatchMode=yes -q "$BUNDLE" "$HOST:/tmp/avalon-$REV.tgz"

echo "== installing on the server"
"${SSH[@]}" "mkdir -p /tmp/avalon-$REV && tar -xzf /tmp/avalon-$REV.tgz -C /tmp/avalon-$REV \
  && sudo bash /tmp/avalon-$REV/deploy/remote.sh install $REV /tmp/avalon-$REV.tgz; \
  rm -rf /tmp/avalon-$REV /tmp/avalon-$REV.tgz"
