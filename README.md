# ResearchMind AI

A personal, autonomous **Research & R&D AI agent**. You describe a research goal;
the system plans it, researches the web across multiple questions, extracts and
scores sources, verifies claims across sources, loops on knowledge gaps, and
produces an evidence-traceable report — all locally.

This is the **Phase 1–6 + partial Phase 7 build** (see `CLAUDE.md` for the full roadmap): a runnable
end-to-end Deep Research pipeline across **six specialized source agents** with claim verification,
duplicate detection, conflict detection, structured R&D analysis, a **semantic knowledge base**,
**report export**, **monitoring**, and **security hardening** — using a **local Ollama** LLM,
persisted to **SQLite** + **Qdrant** (embedded, on-disk).

## What works today

- Create a research project and watch it run live (Server-Sent Events).
- Research Planner → **source-aware parallel dispatch across 6 agents** → finding extraction →
  claim verification → **deduplication** → **conflict detection** → **R&D analysis** →
  knowledge-gap follow-up loop → final Markdown report.
- **Source agents:** Web, Official Documentation, GitHub (repo metadata + activity), Academic
  (arXiv papers), News (recent), Community (forums/Q&A) — pick which to use per project.
- **Research intelligence:** per-source-type reliability scoring, claim statuses & confidence,
  duplicate source/finding removal, contradiction detection (surfaced, never hidden), and automatic
  follow-up research on detected knowledge gaps.
- **R&D intelligence:** a structured solution comparison matrix, an evidence-based recommendation
  with confidence/alternatives/risks, a proof-of-concept, and an implementation roadmap.
- **Knowledge base:** completed research is embedded and indexed for **semantic search**; new
  research surfaces related prior projects; each project gets a **knowledge graph** (topic →
  solutions → recommendation → claims → sources). Falls back to keyword search with no embedding model.
- **Report export** to Markdown, HTML, PDF, and DOCX.
- **Monitoring** page (project/run stats + audit log) and **security hardening**: per-IP rate
  limiting, SSRF-safe outbound fetching, security headers, and an audit trail.
- **Accounts & sign-in:** JWT authentication (register / login), bcrypt-hashed passwords, and
  per-user project ownership so your research is private to your account. Set `AUTH_ENABLED=false`
  to run as a single shared local user with no login.
- **Market Intelligence mode:** ask "what's happening in the market for X right now" and get a
  recency-biased, strictly source-grounded snapshot of the current state (key players, recent
  developments, trends) with an "as of" date — instead of an answer from the model's stale memory.
- **Scheduled research:** save a request and have it run automatically on a recurring cadence
  (hourly / daily / weekly) or as a one-off, with a manual “run now”. Pair it with Market
  Intelligence to keep a live pulse on a topic.
- **Notifications:** in-app alerts when a run finishes, fails, or a schedule fires, with an unread
  badge in the sidebar.
- Pause / resume / stop a run; state persists across restarts (SQLite).
- Dashboard, New Research, live progress with Plan+gaps / Sources / Claims / Conflicts /
  Recommendation / Graph / Report tabs (with export), History, Knowledge Base, and Monitoring.

## Prerequisites

- **Python 3.11+** and **Node 18+**
- **[Ollama](https://ollama.com)** running locally with models pulled:
  ```bash
  ollama pull llama3.1:8b        # reasoning
  ollama pull nomic-embed-text   # embeddings for the knowledge base (optional but recommended)
  ```
  Without the embedding model the app still runs; the knowledge base falls back to keyword search.
- A **web search backend** for the Web, Docs, News, and Community agents — pick one via
  `SEARCH_PROVIDER` in `backend/.env`:
  - **`tavily`** (default): a free **[Tavily](https://app.tavily.com)** API key (`TAVILY_API_KEY`).
  - **`searxng`**: a free, self-hosted **[SearXNG](https://github.com/searxng/searxng)** instance —
    **no API key, no bill**. A ready-made config that enables JSON output lives in `searxng/settings.yml`;
    mount it into the container:
    ```bash
    docker run -d --name searxng -p 8080:8080 \
      -v "$PWD/searxng/settings.yml:/etc/searxng/settings.yml:ro" searxng/searxng
    ```
    Set `SEARCH_PROVIDER=searxng` and `SEARXNG_URL=http://localhost:8080`. This makes ResearchMind
    runnable with **zero paid services** (just Ollama + SearXNG).
- *(Optional)* a GitHub token (`GITHUB_TOKEN`) to raise GitHub API rate limits. The GitHub and
  Academic (arXiv) agents work with no key.

### Behind a corporate TLS-inspecting proxy (Sophos / Zscaler / Netskope)

If your machine decrypts and re-signs HTTPS (common on corporate networks), Python (`httpx`) and the
SearXNG container use their own CA bundle and will reject the proxy's certs with
`CERTIFICATE_VERIFY_FAILED` — every web fetch fails even though your browser works. Two one-time fixes:

1. **Backend** — export your OS trust store (which already trusts the proxy CA) to a PEM bundle and
   point `CA_BUNDLE` at it in `backend/.env`. On Windows PowerShell:
   ```powershell
   $sb = New-Object System.Text.StringBuilder
   Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root | ForEach-Object {
     [void]$sb.AppendLine('-----BEGIN CERTIFICATE-----')
     [void]$sb.AppendLine([Convert]::ToBase64String($_.RawData,'InsertLineBreaks'))
     [void]$sb.AppendLine('-----END CERTIFICATE-----') }
   [IO.File]::WriteAllText('backend\corp-ca-bundle.pem', $sb.ToString())
   ```
   Then set `CA_BUNDLE=corp-ca-bundle.pem`. On startup the app exports `SSL_CERT_FILE` so all outbound
   fetches (content extraction, GitHub, arXiv) verify. The bundle is git-ignored (machine-specific).
2. **SearXNG** — the container's newer OpenSSL may reject a proxy CA whose BasicConstraints aren't
   marked critical. `searxng/settings.yml` sets `outgoing.verify: false` for this reason; the proxy
   already inspects and re-encrypts the traffic, so this is safe on a controlled corporate network.

### Running on CPU (no GPU)

Ollama uses a GPU automatically if present; on **CPU-only** machines an 8B model runs at ~2–4 tok/s, so
a full research run makes dozens of calls and is slow. `backend/.env` ships CPU-friendly defaults —
`OLLAMA_KEEP_ALIVE=30m` (keeps the model resident between steps), `LLM_MAX_TOKENS=1536`,
`SEARXNG_FETCH_CONTENT=false` (snippet-only, skips per-page fetching), and small research budgets
(`MAX_RESEARCH_TASKS`, `MAX_SOURCES_PER_TASK`, `MAX_FOLLOWUP_ROUNDS`). Raise these once you have a GPU
or switch to a faster/cloud provider.

## Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1   |  bash: source .venv/Scripts/activate
.venv/Scripts/python -m pip install -r requirements.txt

cp .env.example .env          # then edit .env: set TAVILY_API_KEY (and OLLAMA_MODEL if needed)

.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- Health (verifies Ollama + Tavily config): http://localhost:8000/health

Run the tests (all offline, no Ollama/Tavily needed):

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
```

## Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /api -> :8000)
```

Open http://localhost:5173. Authentication is on by default: **create an account** (the first one
registered becomes the admin), then go to **New Research**, describe a goal, pick **Deep Research**,
and start. To skip login for a single-user local setup, set `AUTH_ENABLED=false` in `backend/.env`.

A **system-status indicator** on the New Research page (and a dot in the sidebar) shows whether the
backend, Ollama, and your search backend are reachable — with a hint for anything that isn't — so you
know a run will succeed before you start it.

## Configuration

All backend config lives in `backend/.env` (see `.env.example`): Ollama URL/model,
Tavily key, database URL, and research budgets (`MAX_RESEARCH_TASKS`,
`MAX_FOLLOWUP_ROUNDS`, `MAX_SOURCES_PER_TASK`).

## Status & roadmap

Phases 1–6 and nearly all of Phase 7 (export, monitoring, security hardening, JWT authentication,
scheduled research, notifications) are implemented. The only remaining item — see `CLAUDE.md` — is the
optional **Postgres + Redis** swap. The architecture keeps that behind interfaces (LLM provider, search
client, agent dispatch, event bus, scheduler, knowledge/vector store) so it slots in without rework.
