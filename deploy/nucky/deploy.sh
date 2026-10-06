#!/usr/bin/env bash
# Pull the latest code from git and redeploy on nucky (acceptance server).
#
# Installed as /opt/boost-union-envs/deploy.sh -> symlink to this file, so a
# `git pull` of the backend also updates the deploy procedure itself.
#
# Usage: /opt/boost-union-envs/deploy.sh [backend|frontend|all]
set -euo pipefail

ROOT=/opt/boost-union-envs
HERE="$ROOT/backend/deploy/nucky"
target=${1:-all}

deploy_backend() {
  echo '==> backend: git pull'
  cd "$ROOT/backend"
  before=$(git rev-parse HEAD)
  git pull --ff-only
  after=$(git rev-parse HEAD)
  if [ "$before" != "$after" ] && git diff --name-only "$before" "$after" | grep -q pyproject.toml; then
    echo '   pyproject.toml changed -> reinstalling deps'
    "$ROOT/venv/bin/pip" install --upgrade \
      docker fire gitpython loguru dependency-injector pyyaml \
      rich requests mergedeep jinja2 fastapi 'uvicorn[standard]' httpx
  fi

  # systemd unit + reaper cron live in the repo; install them when they differ.
  if ! cmp -s "$HERE/boost-union-api.service" /etc/systemd/system/boost-union-api.service; then
    echo '   installing updated boost-union-api.service'
    install -m 644 "$HERE/boost-union-api.service" /etc/systemd/system/boost-union-api.service
    systemctl daemon-reload
  fi
  if ! cmp -s "$HERE/boost-union-reap.cron" /etc/cron.d/boost-union-reap; then
    echo '   installing updated reaper cron (/etc/cron.d/boost-union-reap)'
    install -m 644 "$HERE/boost-union-reap.cron" /etc/cron.d/boost-union-reap
  fi

  systemctl restart boost-union-api
  systemctl is-active boost-union-api
}

deploy_frontend() {
  echo '==> frontend: git pull'
  cd "$ROOT/frontend"
  # dist/ is committed but rebuilt here; drop the previous local build so the
  # pull never conflicts with it.
  git checkout -- dist
  git clean -fdq dist
  git pull --ff-only
  npm install --no-audit --no-fund --silent
  npx vite build
  echo '   built -> /var/www/html (symlink to dist/)'
}

case "$target" in
  backend)  deploy_backend ;;
  frontend) deploy_frontend ;;
  all)      deploy_backend; deploy_frontend ;;
  *) echo "unknown target: $target"; exit 1 ;;
esac

echo '==> done'
