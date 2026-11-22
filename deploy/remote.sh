#!/usr/bin/env bash
# Runs on the server as root. Called by deploy.sh; see docs/runbook.md.
#
#   remote.sh install <rev> <bundle.tgz>   unpack a release, install, switch to it
#   remote.sh rollback                     switch back to the previous release
set -euo pipefail

ROOT=/opt/avalon
PORT=4177
KEEP=5

health() {
  for _ in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

switch_to() {
  local release="$1"
  ln -sfn "$release" "$ROOT/app.new" && mv -T "$ROOT/app.new" "$ROOT/app"
  ln -sfn "$release/apps/web/dist" "$ROOT/web.new" && mv -T "$ROOT/web.new" "$ROOT/web"
  systemctl restart avalon-api
}

case "${1:-}" in
  install)
    rev="$2"; bundle="$3"
    id avalon >/dev/null 2>&1 || useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin avalon
    install -d -o root -g root -m 755 "$ROOT" "$ROOT/releases"
    install -d -o avalon -g avalon -m 750 "$ROOT/data"

    release="$ROOT/releases/$(date -u +%Y%m%d%H%M%S)-$rev"
    mkdir -p "$release"
    tar -xzf "$bundle" -C "$release"
    chmod -R go-w "$release"

    # Third-party packages only; the code itself runs from the release directory.
    [[ -x "$ROOT/venv/bin/python" ]] || python3 -m venv "$ROOT/venv"
    "$ROOT/venv/bin/python" - "$release/apps/api/pyproject.toml" > "$ROOT/requirements.txt" <<'PY'
import sys, tomllib
print("\n".join(tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]))
PY
    "$ROOT/venv/bin/pip" install --quiet --disable-pip-version-check -r "$ROOT/requirements.txt"

    if [[ ! -f "$ROOT/api.env" ]]; then
      install -o root -g avalon -m 640 "$release/deploy/api.env.example" "$ROOT/api.env"
      echo "Created $ROOT/api.env from the example: put the DeepSeek key in it."
    fi
    install -m 644 "$release/deploy/avalon-api.service" /etc/systemd/system/avalon-api.service
    systemctl daemon-reload
    systemctl enable --quiet avalon-api

    previous="$(readlink -f "$ROOT/app" 2>/dev/null || true)"
    switch_to "$release"
    if ! health; then
      echo "The new release does not answer on /health." >&2
      journalctl -u avalon-api -n 30 --no-pager >&2 || true
      if [[ -n "$previous" && -d "$previous" ]]; then
        echo "Switching back to $previous" >&2
        switch_to "$previous"
      fi
      exit 1
    fi
    # Old releases beyond the last few go.
    ls -1dt "$ROOT"/releases/* | tail -n +$((KEEP + 1)) | xargs -r rm -rf
    echo "Live: $(basename "$release")"
    ;;
  rollback)
    current="$(readlink -f "$ROOT/app")"
    previous="$(ls -1dt "$ROOT"/releases/* | grep -vx "$current" | head -n 1)"
    [[ -n "$previous" ]] || { echo "No earlier release to go back to." >&2; exit 1; }
    switch_to "$previous"
    health && echo "Live: $(basename "$previous")"
    ;;
  *)
    echo "usage: remote.sh install <rev> <bundle> | rollback" >&2
    exit 2
    ;;
esac
