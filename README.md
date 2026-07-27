# AI Content Factory

Dockerized MVP for an automated AI video generation platform.

## Current milestone

- React dashboard for creating video script jobs.
- FastAPI backend with PostgreSQL persistence.
- Optional Cursor agent script generation (cloud runtime).
- Redis and RabbitMQ ready for worker orchestration.
- Nginx reverse proxy.
- Portainer for container management.
- GitHub Actions CI + deploy to Hetzner on `main`.

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

RabbitMQ is internal-only by default. To inspect it later:

```bash
ssh -L 15672:localhost:15672 root@SERVER_IP
```

Then open `http://localhost:15672`.

## CI / CD

- **CI** (`.github/workflows/ci.yml`): validates Compose, compiles the backend, builds the frontend on every PR and push to `main`.
- **Deploy** (`.github/workflows/deploy.yml`): SSHs into the Hetzner server and runs `scripts/deploy.sh` on every push to `main` (or via workflow dispatch).

### Required GitHub secrets

| Secret | Value |
|--------|--------|
| `DEPLOY_HOST` | Server IP (e.g. `2.28.0.8`) |
| `DEPLOY_USER` | SSH user (e.g. `root`) |
| `DEPLOY_SSH_KEY` | Private key used only for deploys |

Manual deploy on the server:

```bash
cd /opt/ai-content-factory
bash scripts/deploy.sh
```

## Enable Cursor agent generation

Create an API key at [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations), then edit `.env`:

```env
CURSOR_API_KEY=cursor_...
CURSOR_MODEL=composer-2.5
```

Restart the backend:

```bash
docker compose up -d --build backend
```

Without a key, the API falls back to a local mock script so the dashboard still works.
