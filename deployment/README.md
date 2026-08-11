# Deployment

Docker-based deployment for the KOC data dashboard: a FastAPI backend and a
Next.js frontend, wired together with `docker compose`.

## Architecture

- **`api`** — FastAPI backend (`api/main.py`), served by gunicorn/uvicorn
  workers. Built from `Dockerfile.api`.
- **`frontend`** — Next.js app, built and run in production mode. Built from
  `Dockerfile.frontend` (multi-stage: build, then a slim runtime image).

No separate reverse proxy container is used. The frontend already proxies
same-origin `/api/*` requests to the backend via the `rewrites()` config in
`frontend/next.config.ts`, so the frontend container is the single public
entrypoint and forwards API calls internally to the `api` service over the
compose network (`API_PROXY_TARGET=http://api:8000`).

## Run locally

```bash
cd deployment
cp .env.example .env
# edit .env as needed (placeholders work out of the box with the sqlite fallback)
docker compose --env-file .env up --build
```

The app is available at `http://localhost:3000` (or `FRONTEND_PORT` if
changed). All `/api/*` requests are transparently forwarded to the backend
container — there is only one origin to expose.

## Run in production

1. Copy `.env.production.example` to `.env.production` and fill in real
   values from your own secret manager — never commit this file.
2. Required variables:
   - `DATABASE_URL` — a real PostgreSQL/Supabase connection string. Without
     it the backend falls back to a local sqlite file, which is not suitable
     for a multi-instance or multi-user production deployment.
   - `TEAM_PASSWORD` — the shared access password checked by the login flow.
3. Optional variables (leave blank to disable the corresponding feature):
   `YOUTUBE_API_KEY`, `AI_PROVIDER`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`,
   `DEEPSEEK_BASE_URL`.
4. Start the stack:

   ```bash
   cd deployment
   docker compose --env-file .env.production up --build -d
   ```

5. Put this behind whatever TLS-terminating load balancer, reverse proxy, or
   ingress controller your hosting environment provides, forwarding traffic
   to the `frontend` container's published port (`FRONTEND_PORT`, default
   `3000`). This setup is self-hostable on any Docker-capable host and is not
   tied to a specific cloud provider.

## Notes

- The `koc-data` named volume persists the sqlite fallback database across
  container restarts when `DATABASE_URL` is left empty. When using a real
  Postgres/Supabase database this volume is unused.
- Never commit `.env`, `.env.production`, or any file containing a real
  connection string or password — only the `.example` files belong in
  version control.
