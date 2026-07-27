#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ai-content-factory}"
BRANCH="${DEPLOY_BRANCH:-main}"

cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env in $APP_DIR — copy from .env.example and configure secrets first."
  exit 1
fi

echo "==> Fetching $BRANCH"
git fetch --prune origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

echo "==> Building and restarting containers"
docker compose up -d --build --remove-orphans
docker compose restart nginx

echo "==> Pruning unused images"
docker image prune -f

echo "==> Health check"
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1/api/health >/dev/null 2>&1; then
    echo "Deploy healthy: $(curl -fsS http://127.0.0.1/api/health)"
    docker compose ps
    exit 0
  fi
  sleep 2
done

echo "Health check failed after deploy"
docker compose ps
docker compose logs --tail=80 backend nginx
exit 1
