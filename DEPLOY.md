# Deploying Deepfield

Deepfield ships as **one web service** (the FastAPI backend serves both the API
and the bundled React frontend) plus a **Postgres database with pgvector**.

- **[Option A — Render](#option-a--render-recommended-free)** — free, Blueprint-driven, recommended.
- **[Option B — Railway](#option-b--railway-paid)** — smooth but needs a card.

---

## Option A — Render (recommended, free)

Render reads [`render.yaml`](render.yaml) and provisions everything: the Docker
web service and a managed Postgres (which supports `pgvector`). ~10 minutes.

### Steps

1. **Push to GitHub** — already done (`shrish186/deepfield`).
2. Go to **[dashboard.render.com](https://dashboard.render.com)** → **New → Blueprint**.
3. **Connect the `deepfield` repo.** Render detects `render.yaml` and shows the
   plan: one web service + one Postgres.
4. It will prompt for the three secret env vars (marked `sync: false`). Paste:
   - `ANTHROPIC_API_KEY`
   - `TAVILY_API_KEY`
   - `VOYAGE_API_KEY` *(optional — leave blank to run without the graph)*
   `JWT_SECRET` is generated for you; `DATABASE_URL` is wired automatically.
5. Click **Apply**. Render builds the Docker image and creates the database.
   First boot runs the schema setup (incl. `CREATE EXTENSION vector`) on its own.
6. Open the web service URL (e.g. `https://deepfield.onrender.com`) → sign up → run a report.

That's it — because the frontend is served by the backend, there's no separate
frontend service, no `VITE_API_URL`, and no CORS to configure.

### Free-tier caveats (be aware)

- **Cold starts:** a free web service **sleeps after ~15 min idle**; the next
  visit takes ~30–60s to wake. Fine for a portfolio; if you want always-on,
  the web service is $7/mo.
- **Database lifespan:** Render's **free Postgres is deleted after 30 days**
  (with email warnings). Upgrade the DB (~$7/mo) to keep it, or recreate it.
- **Memory:** free web is 512 MB RAM — plenty for single-user testing; the
  global daily cap keeps load bounded.

---

## Option B — Railway (paid)

Railway is smooth but its free trial is one-time; once it's "maxed out" you must
add a card (Hobby plan, ~$5/mo usage-based).

1. **New Project → Deploy from GitHub repo** → `deepfield`.
2. Add a **Docker Image** service from `pgvector/pgvector:pg16` (⚠️ *not* the
   default Postgres — it lacks pgvector). Give it a volume at
   `/var/lib/postgresql/data` and `POSTGRES_USER/PASSWORD/DB`.
3. On the app service, set **Root Directory** empty (it builds the root
   `Dockerfile`, the same single-service image), generate a domain, and set the
   env vars below.
4. Deploy.

---

## Environment variables (both hosts)

| Var | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude. |
| `TAVILY_API_KEY` | ✅ | Web search. |
| `VOYAGE_API_KEY` | optional | Enables the disagreement graph. |
| `JWT_SECRET` | ✅ (prod) | Render generates it. Else: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `DEEPFIELD_ENV` | ✅ | `production`. |
| `DATABASE_URL` | ✅ | Render wires it; on Railway use the db service URL. |
| `DEEPFIELD_FREE_DEEP_RUNS` | optional | Per-user monthly deep-run cap (default 3). |
| `DEEPFIELD_GLOBAL_DAILY_DEEP_RUNS` | optional | Global daily ceiling (default 50). |

---

## Protect your wallet

Cost controls are on by default:

- **Per-user:** `DEEPFIELD_FREE_DEEP_RUNS` deep runs/account/month.
- **Global:** `DEEPFIELD_GLOBAL_DAILY_DEEP_RUNS` total deep runs/day — the hard
  ceiling. Lower it any time.
- Basic and chat answers are unmetered.

Also set **spend limits in the Anthropic and Tavily dashboards** as an
independent backstop, and **rotate any key** that has been shown in a screenshot.

**Give yourself unlimited runs:** in your host's Postgres console (Render:
database → **Connect → PSQL**), run:
```sql
UPDATE users SET plan = 'pro' WHERE email = 'you@example.com';
```
The per-user cap is then skipped for you (the global daily ceiling still applies).

---

## Notes

- The research pipeline runs as an in-process background task — run a **single
  instance** (no autoscaling) for now.
- Each push to `main` triggers a redeploy.
- Local development still uses `docker compose up` (frontend + backend as
  separate services); the single-service image is only for deploy.
