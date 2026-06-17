# Deploying Deepfield to Railway

This guide deploys the three pieces — **database**, **backend**, **frontend** —
as three Railway services in one project. Plan for ~15 minutes.

> **Why not Railway's one-click Postgres?** Deepfield's disagreement graph needs
> the `pgvector` extension, which Railway's default Postgres image does not
> include. We deploy Postgres from the official `pgvector/pgvector` image instead
> (step 1). If you skip this, the backend will fail to start on `CREATE EXTENSION
> vector`.

---

## 0. Prerequisites

- A [Railway](https://railway.app) account.
- The repo pushed to GitHub (done: `shrish186/deepfield`).
- Your `ANTHROPIC_API_KEY` and `TAVILY_API_KEY`. Optionally `VOYAGE_API_KEY`
  (enables the graph; the app runs fine without it).
- Generate a JWT secret and keep it handy:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

Create a new Railway **project** (empty). You'll add three services to it.

---

## 1. Database service (pgvector)

1. **New → Empty Service → Deploy from Docker Image** → image:
   `pgvector/pgvector:pg16`
2. In the service **Variables**, set:
   ```
   POSTGRES_USER=deepfield
   POSTGRES_PASSWORD=<a long random password>
   POSTGRES_DB=deepfield
   ```
3. In **Settings → Volumes**, add a volume mounted at:
   ```
   /var/lib/postgresql/data
   ```
   (Without a volume your data is wiped on every redeploy.)
4. Deploy. Note the service name (e.g. `pgvector`) — you'll reference it next.

The internal connection string will be:
```
postgresql://deepfield:<password>@<db-service-name>.railway.internal:5432/deepfield
```

---

## 2. Backend service

1. **New → GitHub Repo →** select `shrish186/deepfield`.
2. **Settings → Root Directory:** `backend`  (Railway builds `backend/Dockerfile`).
3. **Settings → Networking → Generate Domain** — note the URL, e.g.
   `https://deepfield-backend.up.railway.app`.
4. **Variables** (paste your real values):
   ```
   ANTHROPIC_API_KEY=...
   TAVILY_API_KEY=...
   VOYAGE_API_KEY=...            # optional; omit to run without the graph
   JWT_SECRET=...                # the token from step 0 — REQUIRED in prod
   DEEPFIELD_ENV=production
   DATABASE_URL=postgresql://deepfield:<password>@<db-service-name>.railway.internal:5432/deepfield
   DEEPFIELD_FREE_DEEP_RUNS=3
   DEEPFIELD_GLOBAL_DAILY_DEEP_RUNS=50
   ALLOWED_ORIGINS=https://<your-frontend-domain>   # fill in after step 3
   ```
   You won't know the frontend domain yet — set `ALLOWED_ORIGINS` after step 3,
   then redeploy. The backend binds Railway's injected `$PORT` automatically.
5. Deploy. Visit `https://<backend-domain>/health` → should return
   `{"status":"ok"}`, and `/docs` shows the API.

---

## 3. Frontend service

1. **New → GitHub Repo →** select the same repo again.
2. **Settings → Root Directory:** `frontend`.
3. **Settings → Networking → Generate Domain** — this is your app's public URL.
4. **Variables:**
   ```
   VITE_API_URL=https://<your-backend-domain>
   ```
   Railway passes this to the Docker build as the `VITE_API_URL` build arg, so
   the browser bundle talks to your backend. (It's baked in at build time — if
   you change it, redeploy.) nginx binds Railway's `$PORT` automatically.
5. Deploy.

---

## 4. Wire the two together

1. Back on the **backend** service, set
   `ALLOWED_ORIGINS=https://<your-frontend-domain>` and redeploy.
2. Open the frontend domain → create an account → run a deep report.

---

## 5. Protect your wallet

The cost controls are already on:

- **Per-user:** `DEEPFIELD_FREE_DEEP_RUNS` deep runs/account/month.
- **Global:** `DEEPFIELD_GLOBAL_DAILY_DEEP_RUNS` total deep runs/day across
  everyone — the hard ceiling. Lower it any time from the backend Variables.
- Basic and chat answers are unmetered (cheap model, no web fan-out).

Also set **spend limits in the Anthropic and Tavily dashboards** as a backstop —
the app cap and the provider cap are independent safety nets.

**Give yourself unlimited runs:** set your own account's plan to `pro` in the DB
(from Railway's Postgres service → Data tab, or `psql`):
```sql
UPDATE users SET plan = 'pro' WHERE email = 'you@example.com';
```
The per-user cap is then skipped for you (the global daily ceiling still applies).

---

## Notes

- The research pipeline runs as an in-process background task, so run the
  backend as a **single instance** (no horizontal autoscaling) for now.
- Each deploy redeploys from `main`. Push to GitHub → Railway rebuilds.
- Rotate any API key that has ever been shown in a screenshot or committed.
