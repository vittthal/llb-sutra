# Deploying LLB Sutra for free

Total cost: **₹0**. The app uses no paid LLM — retrieval is Postgres full-text plus a
local embedding model — so there is nothing metered to pay for.

## The split that makes it free

Everything expensive runs on your laptop, once:

```
YOUR LAPTOP                                  FREE HOSTING
fetch acts, OCR papers, parse, embed   ──►   Neon Postgres (25 MB of 500 MB)
   (4 GB RAM, Tesseract, PyMuPDF)                   ▲
                                                    │
                                             Render / Koyeb (512 MB)
                                             serves API + frontend only
```

The server never opens a PDF. That is why the runtime image needs no Tesseract, no
Poppler and no PDF libraries, and why 512 MB is enough.

## What to use, and what to avoid

| Piece | Use | Why not the obvious alternative |
|---|---|---|
| Database | **Neon** free — 0.5 GB, pgvector, persistent | **Render's free Postgres is deleted 30 days after creation.** It would take the whole corpus with it. |
| App | **Render** free (512 MB, sleeps after 15 min) or **Koyeb** free (512 MB, sleeps after 1 h, no card) | **Fly.io ended its free tier**; Railway is trial credit, not a free tier. |
| Docker Spaces | — | Hugging Face now requires a **paid** plan for Docker Spaces. |

Your corpus is 25 MB against Neon's 500 MB, so there is roughly 20× headroom for more
semesters.

## Steps

**1. Create a free Neon project** at neon.tech and copy the connection string
(it ends in `?sslmode=require`).

**2. Push the corpus** from your laptop, with the local stack running:

```bash
docker compose up -d db
python -m deploy.push_to_neon "postgresql://…@…neon.tech/…?sslmode=require" --dry-run
python -m deploy.push_to_neon "postgresql://…@…neon.tech/…?sslmode=require"
```

It applies the schema and copies every table in dependency order, converting the
`vector` column through text (asyncpg has no pgvector codec). Re-run with `--reset`
after rebuilding the corpus.

**3. Push the code to GitHub**, then on Render: **New → Blueprint**, select the repo.
`render.yaml` configures the rest. Set `DATABASE_URL` to the Neon string.

**4. Open the URL.** First request after a sleep takes ~1 minute to wake.

## If it runs out of memory

The embedding model is the only large thing in the image (~130 MB model plus
onnxruntime). If the instance OOMs, set:

```
ENABLE_VECTOR_SEARCH=false
```

The site stays fully usable — keyword search, syllabus, past papers, topic analytics
all work. Only semantic matching is lost, and for statutes that is a smaller loss than
it sounds: section numbers and case names are matched lexically anyway.

## Keeping it awake

Free instances sleep. A cron ping every 10 minutes to `/health` keeps Render warm, but
it also burns your 750 free instance-hours per month — 750 hours is under 31 days, so a
service kept permanently awake **will** be suspended before month end. Better to let it
sleep and accept the one-minute wake, unless you are demonstrating it live.

## Updating the corpus later

Ingest locally, then push again:

```bash
python -m ingest.fetch_sources
python -m ingest.load
python -m ingest.embed_missing
python -m deploy.push_to_neon "<neon url>" --reset
```

No redeploy needed — the app reads whatever is in the database.
