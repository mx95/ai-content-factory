# AI Content Factory

Dockerized MVP for an automated AI video generation platform.

## Current milestone

- React dashboard: topic → script → automatic video render → preview → Approve / Reject
- Cursor cloud agent (or mock) for scripts
- Free/local media pipeline with optional OpenAI TTS + DALL·E scene images (falls back to edge-TTS/espeak + Pillow)
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

## Enable OpenAI voice + AI images

Used by the **worker** for narration and scene visuals (script generation still uses Cursor):

```env
OPENAI_API_KEY=sk-...
OPENAI_TTS_MODEL=tts-1-hd
OPENAI_TTS_VOICE=nova
OPENAI_IMAGE_MODEL=dall-e-3
```

```bash
docker compose up -d --build worker backend
```

Without this key, the worker falls back to edge-TTS/espeak and Pillow slides.

## Email notifications

When a render finishes (`ready` or `failed`), the worker can email you.

```env
APP_PUBLIC_URL=http://2.28.0.8
NOTIFY_EMAIL_TO=you@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=you@gmail.com
SMTP_USE_TLS=true
```

For Gmail, create an [App Password](https://myaccount.google.com/apppasswords) (2FA required).
