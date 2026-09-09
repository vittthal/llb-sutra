# LLB Sutra

A syllabus-aligned study platform for Mumbai University LL.B. Semester V, built on a
source-controlled legal corpus: bare acts, judgments from the official reporter,
previous-year questions, and your own notes — retrieved with citations.

Runs entirely on your laptop. No hosting, no domain, no accounts.

## Semester V subjects

| Code | Subject |
|---|---|
| `CPC` | Civil Procedure Code 1908 & Limitation Act 1963 |
| `BNSS` | Bharatiya Nagarik Suraksha Sanhita 2023, Juvenile Justice Act 2015, POCSO Act 2012 |
| `LABOUR2` | Labour Law & Industrial Relations II |
| `PIL` | Public International Law |
| `MOOT` | Moot Court Exercise & Internship |

## Prerequisites

- **Docker Desktop**, running. Everything else lives in containers — you do not need
  Python installed on Windows.
- An Anthropic API key, but **not until Phase 3**. Phases 1 and 2 cost nothing.

## Start

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000 — try `/health`, `/stats`, `/subjects`, `/acts`
- Postgres: `localhost:5432`

The schema in `db/migrations/001_init.sql` is applied automatically the first time the
database volume is created. After changing the schema during development:

```bash
docker compose down -v && docker compose up --build
```

(`-v` drops the data volume. Re-run the ingest afterwards.)

## Loading the corpus

Run these inside the API container:

```bash
docker compose exec api python -m ingest.fetch_sources --dry-run   # check reachability
docker compose exec api python -m ingest.fetch_sources             # download
docker compose exec api python -m ingest.load --skip-embeddings    # structure only, fast
docker compose exec api python -m ingest.load                      # with embeddings
```

`--dry-run` first, always. Government portals move files without notice, and a dry run
tells you which sources need a manual download instead of failing silently mid-load.

## Adding your own PDFs

Two ways, neither requiring you to edit YAML.

**Drop folder.** Layout drives the metadata, so you can bulk-add a whole semester:

```
data/incoming/CPC/notes/res-judicata.pdf     -> subject CPC, doc_type notes
data/incoming/CPC/pyq/nov-2024.pdf           -> subject CPC, doc_type pyq
data/incoming/syllabus/sem5.pdf              -> doc_type syllabus
```

```bash
docker compose exec api python -m ingest.add scan
```

**One file, explicitly:**

```bash
docker compose exec api python -m ingest.add file data/manual/takwani.pdf \
    --title "Takwani, Civil Procedure" --type textbook --subject CPC \
    --licence owned-licensed
```

`python -m ingest.add list` shows everything registered.

Your additions go to `ingest/sources.local.yaml`, which is gitignored. The curated
`ingest/sources.yaml` stays clean, so pulling updates never touches your material.

## Licences — read this before adding books

Every document carries a licence, and it decides what the API may **serve** (as opposed
to what it may **retrieve**):

| Licence | Serves | For |
|---|---|---|
| `public` | full text | UN/ICJ treaties |
| `govt-public` | full text | Indian bare acts, judgments, question papers |
| `owned-licensed` | 200-char excerpt + citation | textbooks and notes you legally own |
| `excerpt-only` | 50-char excerpt + citation | most restricted |

A copyrighted textbook can still improve answers — it is fed to the model as context —
without the platform ever republishing it. This is enforced in
`backend/app/licence.py`, not by a prompt instruction, and an unknown licence value
fails closed at 50 characters. `ingest.add` defaults to `owned-licensed`; widen it
deliberately, per file.

Standard textbooks (Takwani, Mulla, Ratanlal & Dhirajlal, Kailash Rai) are not fetched
by this project. Supply copies you legally own.

## Sources

- **Bare acts** — [India Code](https://indiacode.gov.in/), with MHA and PRS India as
  mirrors. India Code's direct `bitstream` URLs are unstable, so the fetcher falls back
  to its DSpace search API and resolves acts by name.
- **Supreme Court judgments** — [DigiSCR](https://digiscr.sci.gov.in/), the Court's own
  official law report (SCR), free, complete from 1950.
- **High Court judgments** — [judgments.ecourts.gov.in](https://judgments.ecourts.gov.in/),
  and the [AWS Open Data HC dataset](https://registry.opendata.aws/indian-high-court-judgments/)
  for bulk.
- **Treaties** — UN and ICJ.

SCC Online, Manupatra and Indian Kanoon are **not** ingested: the first two are licensed
databases whose headnotes are copyrighted editorial work. Cite them; do not scrape them.

## Tests

```bash
docker compose exec api pytest
```

Covers licence gating (including fail-closed on unknown licences), act parsing, and the
rule that a statutory section is never split across chunks.

## Status

- **Phase 1 — corpus.** Schema, source manifest, fetcher, extractor, act parser,
  chunker, embedder, loader, browse API. *Built; not yet run end-to-end.*
- **Phase 2 — retrieval.** Hybrid vector + full-text search with RRF fusion. *Next.*
- **Phase 3 — LangGraph answering.** Intents, marks-calibrated answers, citation
  verification.
- **Phase 4 — frontend.**
- **Phase 5 — use it for a full semester.**

Full plan: `~/.claude/plans/whimsical-brewing-dolphin.md`
