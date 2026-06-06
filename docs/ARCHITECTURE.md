# ARCHITECTURE.md — 環島中港通酒店套票監察系統

> Format: `.md` | Last updated: 2026-06-06

## System Topology

```
GitHub Actions (cron 0 1 * * *  =  09:00 HKT)
└─► ubuntu-latest runner
     └─► scrape_and_notify.py
          ├─► requests ──► tilchinalink.com/promotions.php?page={1..3}
          ├─► BeautifulSoup ──► promo[] (title, date, content, url)
          ├─► hashlib.sha256 ──► last_hash.txt (in-repo state)
          ├─► prefilter (expiry + keyword exclusion)
          │     └─► skip LLM if all excluded
          ├─► openai SDK ──► OpenRouter /chat/completions
          │     └─► Fallback chain: Qwen3-Next 80B → GLM-4.5-Air → Llama 3.3 70B
          └─► requests POST ──► Discord Incoming Webhook
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
- **Permissions**: `contents: write` (for `last_hash.txt` commit)
- **Secrets (GitHub Secrets)**:
  - `OPENROUTER_API_KEY` · `DISCORD_WEBHOOK_URL`
- **Variables (GitHub Variables)**:
  - `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
  - `OPENROUTER_MODEL_PRIMARY` (default: `qwen/qwen3-next-80b:free`)
  - `OPENROUTER_MODEL_SECONDARY` (default: `z-ai/glm-4.5-air:free`)
  - `OPENROUTER_MODEL_TERTIARY` (default: `meta-llama/llama-3.3-70b-instruct:free`)
- **State**: `last_hash.txt` — 64-char SHA-256 hex
- **Cost**: $0/month (free-tier quotas)

## Data Model & Schema

No traditional database. In-memory per run:

- **`promo dict`** (defined in `scrape_and_notify.py:210-215`):
  - `title: str` — from `<h4><a>` text
  - `date: str` — `YYYY-MM-DD` from parent text
  - `content: str` — body text from `<span class="d-block">`
  - `url: str` — canonicalized absolute URL
- **`last_hash.txt`**: 64-char SHA-256 hex, append-only commits by Actions bot

## Business Rules
- **Eligibility (ALL required)**: hotel stay ≥1 night + transport (bus/coach) + buffet OR breakfast
- **Hard exclusions**: concerts, theme parks, pure-fare promos, top-up rewards, new-route launch
- **Expiry**: end date in content < TODAY → expired; publish date > 180 days old w/o end date → stale
  - ✅ Aligned with `SCOPE.md` FR-6.4 (180 days) since commit `8113ae7`; env-tunable via `PROMO_STALE_DAYS`
- **No-show tolerance**: page unchanged → 0 LLM calls; prefilter eliminates all → 0 LLM calls
- **Output contract**: Discord message ≤2000 chars (truncated to 1950+ellipsis)

## API Contracts
- **OpenRouter**: `POST {base_url}/chat/completions` (OpenAI-compatible), `timeout=90s`
- **Discord**: `POST {webhook_url}` JSON `{"username", "content"}`, `timeout=10s`
- **Target site**: `GET {BASE_URL}[?page=N]`, `timeout=30s`, requires browser `User-Agent`

## Known Architectural Risks
- 🟡 Hash covers raw page text including ads/counters — false-positive change triggers LLM
- 🟡 Date parsing limited to 3 regex patterns — coverage gaps for no-year or slash formats
- 🟡 Single-region dependency on OpenRouter free-tier stability (no Anthropic/OpenAI/Google fallback)
- 🟢 No retry on Discord webhook failure (silent loss of notification)
