# CONTEXT-MAP.md — File Navigation Index

> Format: `.md` | Last updated: 2026-06-06
> Primary navigation index. Load only files listed here unless task requires broader scan.

## Module Mappings

| Path | Responsibility | Last Modified | Validation |
|---|---|---|---|
| `scrape_and_notify.py` | Entry point: scrape → hash → prefilter → LLM → Discord | 2026-04-27 | ✅ Compiles |
| `.github/workflows/hotel-monitor.yml` | Daily cron + manual dispatch, hash commit | 2026-04-27 | ✅ Valid YAML |
| `requirements.txt` | Pinned Python deps (3 packages) | 2026-04-27 | ✅ |
| `last_hash.txt` | SHA-256 state for change detection | 2026-04-27 | ✅ 64 hex chars |
| `README.md` | User-facing setup + behaviour docs | 2026-04-27 | ✅ |
| `AGENTS.md` | Project workflow rules + AI directives | 2026-06-06 | ✅ |
| `project-documents/Requirements.md` | Source for SCOPE (FR-1 to FR-6, NFRs) | 2026-04-27 | ✅ Mirrored to docs/SCOPE.md |
| `project-documents/ImplementationPlan.md` | Source for PLAN (T1–T8 tasks) | 2026-04-27 | ✅ Mirrored to docs/PLAN.md |
| `docs/SCOPE.md` | Upstream requirements baseline (immutable) | 2026-04-27 | ✅ |
| `docs/PLAN.md` | Upstream implementation plan (immutable) | 2026-04-27 | ✅ |
| `docs/ARCHITECTURE.md` | System topology + business rules | 2026-06-06 | ✅ |
| `docs/CHANGE-LOG.md` | Session summaries (rolling 14d) | 2026-06-06 | ✅ |
| `docs/DB-SCHEMA.md` | N/A marker (no database in project) | 2026-06-06 | ✅ |
| `docs/CONTEXT-MAP.md` | This file | 2026-06-06 | ✅ |
| `docs/DESIGN.md` | **Not applicable** — no UI; skip | — | ⚠️ Absent by design |

## File Responsibilities

- [x] `scrape_and_notify.py:127-170` `extract_end_dates` — 3-pattern Chinese date regex (validated: structure present)
- [x] `scrape_and_notify.py:177-215` `parse_promotion` — HTML → `promo` dict
- [x] `scrape_and_notify.py:218-238` `fetch_page` — single-page HTTP fetch + parse
- [x] `scrape_and_notify.py:241-260` `scrape_all_pages` — 3-page loop with 1.5s delay
- [x] `scrape_and_notify.py:267-329` `prefilter` (expiry + keyword) — see CHANGE-LOG for FR-1.3 gap
- [x] `scrape_and_notify.py:351-365` `compute_hash` / `load_last_hash` / `save_hash` — change detection
- [x] `scrape_and_notify.py:372-406` `call_llm` — 3-model fallback chain
- [x] `scrape_and_notify.py:413-512` `post_to_discord` / `build_*_message` — notification formatting
- [x] `scrape_and_notify.py:519-613` `main` — orchestration entry point

## Validation Status

- ✅ `requirements.txt` — 3 packages, compatible with Python 3.12
- ✅ `scrape_and_notify.py` — Python 3.12 syntax (py_compile equivalent)
- ✅ `.github/workflows/hotel-monitor.yml` — valid YAML, cron + dispatch triggers
- ⚠️ `scrape_and_notify.py:247` — FR-1.3 early-stop **NOT implemented** (scrapes all 3 pages regardless)
- ⚠️ `scrape_and_notify.py:66` — `PROMO_STALE_DAYS=60` mismatches `SCOPE.md` FR-6.4 (180 days)
- ⚠️ Hash sensitivity — see `ARCHITECTURE.md` Known Risks
