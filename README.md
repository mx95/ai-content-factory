# AI Content Factory

Dockerized MVP for an automated AI video generation platform.

## Current milestone

- React dashboard: topic → script → automatic video render → preview → Approve / Reject
- Cursor cloud agent (or mock) for scripts
- Free/local media pipeline: edge-TTS (espeak-ng fallback) + Pillow scene images + SRT + FFmpeg 1080×1920 MP4
- RabbitMQ worker (`worker` service)
- PostgreSQL, Redis, Nginx, Portainer
- GitHub Actions CI + deploy to Hetzner on `main`

## Run on the server

```bash
cd /opt/ai-content-factory
cp .env.example .env
docker compose up -d --build
```

Then open:

- App: `http://SERVER_IP`
- API health: `http://SERVER_IP/api/health`
- Portainer: `https://SERVER_IP:9443`

## Flow

1. Enter a topic in the dashboard
2. Backend generates a script (Cursor agent if `CURSOR_API_KEY` is set)
3. A `videos` job is queued on RabbitMQ
4. Worker builds narration, scene images, captions, thumbnail, and `final.mp4`
5. Dashboard polls until status is `ready`, then you Approve / Reject / Regenerate

Media files are served from `/api/media/{video_id}/final.mp4`.

## CI / CD

- **CI**: validates Compose, compiles backend, builds frontend on PRs
- **Deploy**: SSH deploy via `scripts/deploy.sh` on push to `main`

Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`

## Enable Cursor agent generation

```env
CURSOR_API_KEY=crsr_...
CURSOR_MODEL=composer-2.5
```

```bash
docker compose up -d --build backend
```

Without a key, scripts use a local mock so the pipeline still runs.

## Optional voice override

```env
EDGE_TTS_VOICE=en-US-JennyNeural
```
