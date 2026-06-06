# ARCHITECTURE.md — 環島中港通酒店套票監察系統

> Format: `.md` | Last updated: 2026-06-06

## System Topology

```
GitHub Actions (cron 0 1 * * *  =  09:00 HKT)
└─► ubuntu-latest runner
     ├─► [job: monitor]      contents: read   + persist-credentials: false
     │   └─► scrape_and_notify.py
     │        ├─► requests ──► tilchinalink.com/promotions.php?page={1..3}  (parallel via ThreadPoolExecutor)
     │        ├─► BeautifulSoup ──► promo[] (title, date, content, url)
     │        ├─► hashlib.sha256 ──► last_hash.txt (in-repo state, no write)
     │        ├─► prefilter (expiry + keyword + hotel-keyword + 2nd-round heuristic)
     │        │     └─► skip LLM if all excluded
     │        ├─► openai SDK ──► OpenRouter /chat/completions
     │        │     └─► Fallback chain: Qwen3-Next 80B → GLM-4.5-Air → Llama 3.3 70B
     │        │     └─► self-consistency (default 2 runs) × URL-retry (default 1)
     │        └─► requests POST ──► Discord Incoming Webhook  (3× retry, exponential backoff)
     │   └─► upload-artifact (last_hash.txt + last_promos.json)
     │
     ├─► [job: commit-hash]   contents: write   needs: monitor
     │   └─► download-artifact ──► git add last_hash.txt last_promos.json ──► git commit [skip ci] ──► git push
     │
     └─► [job: evaluate]      contents: read    (workflow_dispatch only)
         └─► python -m evaluation.evaluate  (golden set 20/20)
```

## Tech Stack & Dependencies
- **Language**: Python 3.12
- **Runtime deps** (`requirements.txt`):
  - `requests>=2.32` — HTTP client (scraping + Discord)
  - `beautifulsoup4>=4.12` — HTML parsing
  - `openai>=1.30` — OpenRouter-compatible client
- **CI**: GitHub Actions `ubuntu-latest`, Python 3.12, pip cache
- **External services**:
  - Target: `tilchinalink.com/promotions.php` (server-rendered PHP, static HTML)
  - LLM gateway: OpenRouter.ai free tier (HK account — Anthropic/OpenAI/Google excluded)
  - Notification: Discord Incoming Webhook

## Deployment & Infra
- **Trigger**: cron `0 1 * * *` + `workflow_dispatch`
- **Timeout**: 10 min
- **Job topology (T9.6.4)**: 3 jobs — `monitor` (read-only) → `commit-hash` (write) + `evaluate` (read, manual only)
- **State transfer**: `actions/upload-artifact@v4` / `download-artifact@v4` (last_hash.txt + last_promos.json)
- **Secrets (GitHub Secrets)**:
  - `OPENROUTER_API_KEY` · `DISCORD_WEBHOOK_URL`
- **Variables (GitHub Variables)**:
  - `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
  - `OPENROUTER_MODEL_PRIMARY` (default: `qwen/qwen3-next-80b:free`)
  - `OPENROUTER_MODEL_SECONDARY` (default: `z-ai/glm-4.5-air:free`)
  - `OPENROUTER_MODEL_TERTIARY` (default: `meta-llama/llama-3.3-70b-instruct:free`)
  - `PROMO_STALE_DAYS` (default: `180`) · `SELF_CONSISTENCY_RUNS` (default: `2`) · `URL_RETRY_LIMIT` (default: `1`)
  - `DISCORD_RETRY_MAX` (default: `3`) · `DISCORD_RETRY_BACKOFF` (default: `2`) · `DRY_RUN` (default: empty)
- **State**: `last_hash.txt` (64-char SHA-256 hex) + `last_promos.json` (full promo list, ~3–5 KB)
- **Cost**: $0/month (free-tier quotas)

## Data Model & Schema

No traditional database. In-memory per run + 2 persistent in-repo files:

- **`promo dict`** (defined in `scrape_and_notify.py:338-369`):
  - `title: str` — from `<h4><a>` text
  - `date: str` — `YYYY-MM-DD` from parent text
  - `content: str` — body text from `<span class="d-block">`
  - `url: str` — canonicalized absolute URL
- **`last_hash.txt`**: 64-char SHA-256 hex, append-only commits by Actions bot (commit-hash job)
- **`last_promos.json`**: full `promo[]` list, used by T9.6.3 for added/removed diff
- **Structured log lines** (`_log_event`): JSON Lines with `{ts, level, run_id, event, ...fields}` — stdout, no persistence

## Business Rules
- **Eligibility (ALL required)**: hotel stay ≥1 night + transport (bus/coach) + buffet OR breakfast
- **Hard exclusions**: concerts, theme parks, pure-fare promos, top-up rewards, new-route launch
- **Expiry**: end date in content < TODAY → expired; publish date > 180 days old w/o end date → stale
  - ✅ Aligned with `SCOPE.md` FR-6.4 (180 days) since commit `8113ae7`; env-tunable via `PROMO_STALE_DAYS`
- **No-show tolerance**: page unchanged → 0 LLM calls; prefilter eliminates all → 0 LLM calls
- **Discord reliability** (T9.6.1): exponential-backoff retry (`DISCORD_RETRY_MAX=3`, `backoff=2s/4s`)
- **Test mode** (T9.6.5): `DRY_RUN=true` → no HTTP, only structured log
- **Output contract**: Discord message ≤2000 chars (truncated to 1950+ellipsis)

## API Contracts
- **OpenRouter**: `POST {base_url}/chat/completions` (OpenAI-compatible), `timeout=90s`, `response_format={"type":"json_object"}`
- **Discord**: `POST {webhook_url}` JSON `{"username", "content"}`, `timeout=10s`, retry x3 with exponential backoff
- **Target site**: `GET {BASE_URL}[?page=N]` (parallel via ThreadPoolExecutor, max_workers=3), `timeout=30s`, requires browser `User-Agent`
- **Log schema** (T9.6.2): JSON Lines to stdout — `{ts: ISO8601Z, level: INFO, run_id: 12-char-hex, event: snake_case, ...}`

## Known Architectural Risks
- 🟡 Single-region dependency on OpenRouter free-tier stability (no Anthropic/OpenAI/Google fallback)
- 🟡 `last_promos.json` parse failure on first run after git history rewrite → `load_last_promos()` returns `[]` (safe)
- 🟢 `RUN_ID` collision unlikely but possible if env not set (UUID4 12-char = 48 bits)
