#!/usr/bin/env bash
set -euo pipefail
cd /opt/ai-content-factory

if grep -q '^CURSOR_API_KEY=.\+' .env; then
  cp .env .env.bak-verify
fi
sed -i 's/^CURSOR_API_KEY=.*/CURSOR_API_KEY=/' .env
docker compose up -d --force-recreate backend
sleep 5
curl -fsS http://127.0.0.1/api/health
echo

RESP=$(curl -fsS -X POST http://127.0.0.1/api/scripts \
  -H 'Content-Type: application/json' \
  -d '{"topic":"Why do cats purr?","language":"English","duration_seconds":30,"niche":"Did You Know"}')
echo "$RESP"
VIDEO_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["video_id"])' <<<"$RESP")
echo "VIDEO_ID=$VIDEO_ID"

STATE=""
for i in $(seq 1 90); do
  STATUS=$(curl -fsS "http://127.0.0.1/api/videos/$VIDEO_ID")
  STATE=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])' <<<"$STATUS")
  echo "[$i] status=$STATE"
  if [ "$STATE" = "ready" ] || [ "$STATE" = "failed" ]; then
    echo "$STATUS"
    break
  fi
  sleep 5
done

if [ -f .env.bak-verify ]; then
  cp .env.bak-verify .env
  docker compose up -d --force-recreate backend
  sleep 3
fi
curl -fsS http://127.0.0.1/api/health
echo
ls -la "storage/videos/$VIDEO_ID/" || true
docker compose logs --tail=40 worker

if [ "$STATE" != "ready" ]; then
  echo "E2E FAILED with status=$STATE"
  exit 1
fi

curl -fsS -X POST "http://127.0.0.1/api/videos/$VIDEO_ID/approve"
echo
echo "E2E OK"
