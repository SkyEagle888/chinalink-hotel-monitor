# CONTEXT-MAP.md — File Navigation Index

> Format: `.md` | Last updated: 2026-06-17
> Primary navigation index. Load only files listed here unless task requires broader scan.

## Module Mappings

| Path | Responsibility | Last Modified | Validation |
|---|---|---|---|
| `scrape_and_notify.py` | Entry point: scrape → hash → prefilter (region+keywords+expired) → fetch_detail_pages → Discord | 2026-06-17 | ✅ 60 unit tests |
| `.github/workflows/hotel-monitor.yml` | 3-job workflow (monitor / commit-hash / evaluate), scoped permissions | 2026-06-06 | ✅ Valid YAML, 3 jobs |
| `requirements.txt` | Pinned Python deps (3 packages) | 2026-04-27 | ✅ |
| `last_hash.txt` | SHA-256 state for change detection (in-repo) | 2026-06-17 | ✅ 64 hex chars |
| `last_promos.json` | Full promo list for T9.6.3 diff tracking (in-repo) | 2026-06-17 | ✅ auto-managed |
| `README.md` | User-facing setup + behaviour docs | 2026-06-17 | ✅ |
| `AGENTS.md` | Project workflow rules + AI directives | 2026-06-06 | ✅ |
| `tests/test_t9.py` | 60 unittest cases (v1.3 regression suite) | 2026-06-17 | ✅ 60/60 pass |
| `tests/__init__.py` | Package marker for `python -m unittest tests.test_t9` | 2026-06-06 | ✅ |
| `evaluation/evaluate.py` | Golden-set evaluator (20 labeled examples) | 2026-06-17 | ✅ 20/20 (100%) |
| `evaluation/golden_set.jsonl` | 20 labeled examples (11 hotel-in-region / 9 exclude) | 2026-06-17 | ✅ |
| `evaluation/__init__.py` | Package marker for `python -m evaluation.evaluate` | 2026-06-06 | ✅ |
| `project-documents/Requirements.md` | Source for SCOPE (FR-1 to FR-6, NFRs) | 2026-04-27 | ✅ Mirrored to docs/SCOPE.md |
| `project-documents/ImplementationPlan.md` | Source for PLAN (T1–T8 tasks) | 2026-04-27 | ✅ Mirrored to docs/PLAN.md |
| `docs/SCOPE.md` | Upstream requirements baseline (§1–§9 immutable, §10 v1.2, §11 v1.3 additive) | 2026-06-17 | ✅ |
| `docs/PLAN.md` | Implementation plan (T1–T10 all `[x]`) | 2026-06-17 | ✅ |
| `docs/ARCHITECTURE.md` | System topology + data model + business rules | 2026-06-17 | ✅ |
| `docs/CHANGE-LOG.md` | Session summaries (rolling 14d, 15KB trim threshold) | 2026-06-17 | ✅ |
| `docs/DB-SCHEMA.md` | N/A marker (no database in project) | 2026-06-06 | ✅ |
| `docs/CONTEXT-MAP.md` | This file | 2026-06-17 | ✅ |
| `docs/DESIGN.md` | **Not applicable** — no UI; skip | — | ⚠️ Absent by design |

## File Responsibilities

- [x] `scrape_and_notify.py:80-150` `_safe_date` / `extract_end_dates` — 7 Chinese date regex patterns (T9.3.1, retained)
- [x] `scrape_and_notify.py:160-205` `parse_promotion` — v1.3 card grid HTML `<a class="package-wrapper">` → promo dict (title/region/price/url)
- [x] `scrape_and_notify.py:210-238` `fetch_page` — single-page HTTP fetch + dynamic-class decompose (T9.1.3, MAX_PAGES=1)
- [x] `scrape_and_notify.py:240-290` `_is_page_stale` / `scrape_all_pages` — 1-page parallel with early-stop
- [x] `scrape_and_notify.py:295-378` `fetch_detail_page` / `fetch_detail_pages` — v1.3 parallel detail-page enrichment (date/nights/dining/transport/room_type)
- [x] `scrape_and_notify.py:383-453` `is_expired` / `is_obviously_non_hotel` / `has_hotel_keyword` / `region_allowed` / `prefilter` (T10.3 region filter added)
- [x] `scrape_and_notify.py:458-525` `compute_hash` / `load_last_hash` / `save_hash` / `load_last_promos` / `save_last_promos` / `compute_promo_diff` / `compute_per_page_hashes` (T9.6.3, unchanged)
- [x] `scrape_and_notify.py:530-640` `sort_by_region` / `group_by_region` / `_render_package_block` / `build_discord_message` / `build_stats_footer` / `build_no_packages_message` (v1.3 region-grouped Discord output)
- [x] `scrape_and_notify.py:645-720` `post_to_discord` (T9.6.1 retry + T9.6.5 DRY_RUN — unchanged)
- [x] `scrape_and_notify.py:725-845` `main` — v1.3 orchestration (no LLM step)
- [x] `scrape_and_notify.py:115-135` `_log_event` + `_STRUCT_LOGGER` — T9.6.2 JSON Lines logger (unchanged)

## Validation Status

- ✅ `requirements.txt` — 3 packages, compatible with Python 3.12
- ✅ `scrape_and_notify.py` — `py_compile` + **60 unit tests** (v1.3 refactor; LLM tests removed, region/card/detail tests added)
- ✅ `.github/workflows/hotel-monitor.yml` — valid YAML, 3 jobs with scoped permissions
- ✅ T9.1.1 / 9.1.2 / 9.1.3 implemented (`_is_page_stale`, `PROMO_STALE_DAYS=180`, `DYNAMIC_CLASS_PATTERN` decompose)
- ✅ T9.3.x / 9.4.x / 9.5.x implemented (date regex, whitelist, parallel scrape, eval set — retained)
- ✅ T9.6.x implemented (Discord retry, JSON logger, promo diff, scoped permissions, DRY_RUN — retained)
- ✅ T10.1–T10.8 implemented (BASE_URL switch, region whitelist, EXCLUDE_KEYWORDS trimmed, detail-page parallel fetch, region-grouped Discord, LLM removed, golden set + tests rewritten)
- ✅ `evaluation/evaluate.py` — **20/20 (100% accuracy)** on new hotel_packages.php golden set
