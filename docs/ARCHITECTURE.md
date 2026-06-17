# ARCHITECTURE.md — 環島中港通酒店套票監察系統

> Format: `.md` | Last updated: 2026-06-17

## System Topology (v1.3)

```
GitHub Actions (cron 0 1 * * *  =  09:00 HKT)
└─► ubuntu-latest runner
     ├─► [job: monitor]      contents: read   + persist-credentials: false
     │   └─► scrape_and_notify.py
     │        ├─► requests ──► tilchinalink.com/hotel_packages.php?lang=tc  (single page, ThreadPoolExecutor)
     │        ├─► BeautifulSoup ──► card[] (title, region, price, url) from <a class="package-wrapper">
     │        ├─► hashlib.sha256 ──► last_hash.txt (in-repo state, no write)
     │        ├─► prefilter (region whitelist → expiry → ski-keyword → hotel-keyword)
     │        ├─► fetch_detail_pages ──► promotions.php?id=XXX (parallel via ThreadPoolExecutor, max_workers=4)
     │        │     └─► enrich each card with date / nights / dining / transport / room_type
     │        ├─► sort_by_region + group_by_region
     │        └─► requests POST ──► Discord Incoming Webhook  (3× retry, exponential backoff)
     │   └─► upload-artifact (last_hash.txt + last_promos.json)
     │
     ├─► [job: commit-hash]   contents: write   needs: monitor
     │   └─► download-artifact ──► git add last_hash.txt last_promos.json ──► git commit [skip ci] ──► git push
     │
     └─► [job: evaluate]      contents: read    (workflow_dispatch only)
         └─► python -m evaluation.evaluate  (golden set 20/20)
```

> 📌 **v1.3 變更**：移除 OpenRouter LLM 調用；新增 detail-page 並行抓取；新增地區白名單過濾。

## Tech Stack & Dependencies
- **Language**: Python 3.12
- **Runtime deps** (`requirements.txt`):
  - `requests>=2.32` — HTTP client (scraping + Discord)
  - `beautifulsoup4>=4.12` — HTML parsing
  - `openai>=1.30` — **保留以備未來 LLM 重新啟用**（v1.3 不再使用）
- **CI**: GitHub Actions `ubuntu-latest`, Python 3.12, pip cache
- **External services**:
  - Target: `tilchinalink.com/hotel_packages.php?lang=tc` (server-rendered PHP, static HTML, no JS)
  - LLM gateway: **v1.3 不再調用**（OpenRouter.ai 環境變量保留供 v1.4）
  - Notification: Discord Incoming Webhook

## Deployment & Infra
- **Trigger**: cron `0 1 * * *` + `workflow_dispatch`
- **Timeout**: 10 min
- **Job topology (T9.6.4)**: 3 jobs — `monitor` (read-only) → `commit-hash` (write) + `evaluate` (read, manual only)
- **State transfer**: `actions/upload-artifact@v4` / `download-artifact@v4` (last_hash.txt + last_promos.json)
- **Secrets (GitHub Secrets)**:
  - `DISCORD_WEBHOOK_URL` — 必需
  - `OPENROUTER_API_KEY` — **v1.3 不再需要**（可保留或刪除）
- **Variables (GitHub Variables)**:
  - `PROMO_STALE_DAYS` (default: `180`)
  - `DISCORD_RETRY_MAX` (default: `3`) · `DISCORD_RETRY_BACKOFF` (default: `2`)
  - `DETAIL_FETCH_TIMEOUT` (default: `15`) · `DETAIL_FETCH_WORKERS` (default: `4`) — **v1.3 新增**
  - `DRY_RUN` (default: empty)
  - `OPENROUTER_*` — **v1.3 不再使用**（可保留或刪除）
- **State**: `last_hash.txt` (64-char SHA-256 hex) + `last_promos.json` (full card list, ~2–4 KB)
- **Cost**: $0/month — **v1.3 完全無 API 成本**（連 OpenRouter 也不調用）

## Data Model & Schema

No traditional database. In-memory per run + 2 persistent in-repo files:

- **`promo dict`** (defined in `scrape_and_notify.py:160-205`) — **v1.3 schema**:
  - `title: str` — from `<h3 class="package-card-title">`
  - `region: str` — from `<span class="package-location">📍 City</span>`
  - `price: str` — from `<span class="package-price">$XXX</span>` + `<span class="package-unit">`
  - `url: str` — canonicalized absolute URL (promotions.php?id=XXX)
  - `date: str` — `YYYY-MM-DD` from detail page (after fetch_detail_pages enrichment)
  - `summary: str` — text content from detail page (faintivory-background div)
  - `nights: int | None` — from detail page regex
  - `dining: str | None` — from detail page regex (自助餐/早餐)
  - `transport: str | None` — from detail page regex (直通巴士)
  - `room_type: str | None` — from detail page regex (標準房/大床房)
- **`last_hash.txt`**: 64-char SHA-256 hex, append-only commits by Actions bot (commit-hash job)
- **`last_promos.json`**: full `promo[]` list, used by T9.6.3 for added/removed diff
- **Structured log lines** (`_log_event`): JSON Lines with `{ts, level, run_id, event, ...fields}` — stdout, no persistence

## Business Rules (v1.3)
- **Region whitelist** (T10.3): `INCLUDE_REGIONS = ["深圳", "廣州", "中山", "珠海"]` — 卡片 region 不在清單內則排除
- **Hard exclusions** (T10.4): only `["滑雪", "雪場", "雪場套票"]` — 廣州滑雪套票依 SCOPE §3.2 排除
- **Eligibility check** (residual): `has_hotel_keyword()` — title/content/summary 至少含「住宿/入住/房間/房」一項
- **Expiry**: end date in content/summary < TODAY → expired; publish date > 180 days w/o end date → stale
  - ✅ Aligned with `SCOPE.md` FR-6.4 (180 days); env-tunable via `PROMO_STALE_DAYS`
- **No-show tolerance**: page unchanged → 0 Discord posts; prefilter eliminates all → "今日無酒店套票"
- **Discord reliability** (T9.6.1): exponential-backoff retry (`DISCORD_RETRY_MAX=3`, `backoff=2s/4s`)
- **Test mode** (T9.6.5): `DRY_RUN=true` → no HTTP, only structured log
- **Output contract**: Discord message ≤2000 chars (truncated to 1950+ellipsis)

## API Contracts (v1.3)
- **Discord**: `POST {webhook_url}` JSON `{"username", "content"}`, `timeout=10s`, retry x3 with exponential backoff
- **Target site (main page)**: `GET {BASE_URL}` (single page, no pagination), `timeout=30s`, browser `User-Agent`
- **Target site (detail pages)**: `GET {promotions.php?id=XXX}` (parallel via ThreadPoolExecutor, max_workers=4), `timeout=15s` (env: `DETAIL_FETCH_TIMEOUT`)
- **Log schema** (T9.6.2): JSON Lines to stdout — `{ts: ISO8601Z, level: INFO, run_id: 12-char-hex, event: snake_case, ...}`
- **OpenRouter**: **不再調用**（v1.3）

## Known Architectural Risks (v1.3)
- 🟡 Detail-page fetch 失敗時 fallback 為 card-only 顯示（訊息資訊較少）
- 🟡 `INCLUDE_REGIONS` 寫死於源碼（如需變更需修改源碼 + 重新部署）
- 🟡 `last_promos.json` parse failure on first run after git history rewrite → `load_last_promos()` returns `[]` (safe)
- 🟢 `RUN_ID` collision unlikely but possible if env not set (UUID4 12-char = 48 bits)
