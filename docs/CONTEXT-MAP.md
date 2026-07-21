# CONTEXT-MAP.md — File Navigation Index

> Format: `.md` | Last updated: 2026-07-21
> Primary navigation index. Load only files listed here unless task requires broader scan.

## Module Mappings

| Path | Responsibility | Last Modified | Validation |
|---|---|---|---|
| `scrape_and_notify.py` | Entry point: scrape → hash → prefilter (region+keywords+expired) → fetch_detail_pages → **Discord (v1.3.1: skip if empty)** | 2026-07-21 | ✅ 66 unit tests |
| `.github/workflows/hotel-monitor.yml` | 3-job workflow (monitor / commit-hash / evaluate), scoped permissions | 2026-06-06 | ✅ Valid YAML, 3 jobs |
| `requirements.txt` | Pinned Python deps (3 packages) | 2026-04-27 | ✅ |
| `last_hash.txt` | SHA-256 state for change detection (in-repo) | 2026-07-21 | ✅ 64 hex chars |
| `last_promos.json` | Full promo list for T9.6.3 diff tracking (in-repo) | 2026-07-21 | ✅ auto-managed |
| `README.md` | User-facing setup + behaviour docs | 2026-07-21 | ✅ |
| `AGENTS.md` | Project workflow rules + AI directives | 2026-06-06 | ✅ |
| `tests/test_t9.py` | 66 unittest cases (v1.3.1 regression suite: +6 TestNoPromotionsSkip) | 2026-07-21 | ✅ 66/66 pass |
| `tests/__init__.py` | Package marker for `python -m unittest tests.test_t9` | 2026-06-06 | ✅ |
| `evaluation/evaluate.py` | Golden-set evaluator (20 labeled examples) | 2026-06-17 | ✅ 20/20 (100%) |
| `evaluation/golden_set.jsonl` | 20 labeled examples (11 hotel-in-region / 9 exclude) | 2026-06-17 | ✅ |
| `evaluation/__init__.py` | Package marker for `python -m evaluation.evaluate` | 2026-06-06 | ✅ |
| `project-documents/Requirements.md` | Source for SCOPE (FR-1 to FR-6, NFRs) | 2026-04-27 | ✅ Mirrored to docs/SCOPE.md |
| `project-documents/ImplementationPlan.md` | Source for PLAN (T1–T8 tasks) | 2026-04-27 | ✅ Mirrored to docs/PLAN.md |
| `docs/SCOPE.md` | Upstream requirements baseline (§1–§9 immutable, §10 v1.2, §11 v1.3 additive, §7 v1.3.1 跳過 Discord) | 2026-07-21 | ✅ |
| `docs/PLAN.md` | Implementation plan (T1–T11 all `[x]`) | 2026-07-21 | ✅ |
| `docs/ARCHITECTURE.md` | System topology + data model + business rules (v1.3.1 no-show tolerance updated) | 2026-07-21 | ✅ |
| `docs/CHANGE-LOG.md` | Session summaries (rolling 14d, 15KB trim threshold) | 2026-07-21 | ✅ |
| `docs/DB-SCHEMA.md` | N/A marker (no database in project) | 2026-06-06 | ✅ |
| `docs/CONTEXT-MAP.md` | This file | 2026-07-21 | ✅ |
| `docs/DESIGN.md` | **Not applicable** — no UI; skip | — | ⚠️ Absent by design |

## File Responsibilities

- [x] `scrape_and_notify.py:133-150` `_safe_date` / `extract_end_dates` — 7 Chinese date regex patterns (T9.3.1, retained)
- [x] `scrape_and_notify.py:232-262` `parse_promotion` — v1.3 card grid HTML `<a class="package-wrapper">` → promo dict (title/region/price/url)
- [x] `scrape_and_notify.py:264-291` `fetch_page` — single-page HTTP fetch + dynamic-class decompose (T9.1.3, MAX_PAGES=1)
- [x] `scrape_and_notify.py:293-353` `_is_page_stale` / `scrape_all_pages` — 1-page parallel with early-stop
- [x] `scrape_and_notify.py:355-458` `fetch_detail_page` / `fetch_detail_pages` — v1.3 parallel detail-page enrichment (date/nights/dining/transport/room_type)
- [x] `scrape_and_notify.py:460-576` `is_expired` / `is_obviously_non_hotel` / `has_hotel_keyword` / `region_allowed` / `prefilter` (T10.3 region filter added)
- [x] `scrape_and_notify.py:578-640` `compute_hash` / `load_last_hash` / `save_hash` / `load_last_promos` / `save_last_promos` / `compute_promo_diff` / `compute_per_page_hashes` (T9.6.3, unchanged)
- [x] `scrape_and_notify.py:642-778` `_render_package_block` / `_build_region_section` / `sort_by_region` / `group_by_region` / `build_stats_footer` / `build_discord_message` (**v1.3.1**: 簡化 — 移除空列表分支；`build_no_packages_message` 已刪除)
- [x] `scrape_and_notify.py:780-845` `post_to_discord` (T9.6.1 retry + T9.6.5 DRY_RUN — unchanged)
- [x] `scrape_and_notify.py:847-893` `main` — v1.3.1 orchestration (**新增**: 步驟 5 `if not filtered: skip Discord` 邏輯)
- [x] `scrape_and_notify.py:112-130` `_log_event` + `_STRUCT_LOGGER` — T9.6.2 JSON Lines logger (unchanged)
- [x] `tests/test_t9.py:703-830` `TestNoPromotionsSkip` — T11.3.1 新增 6 案例（v1.3.1 跳過 Discord 行為）

## Validation Status

- ✅ `requirements.txt` — 3 packages, compatible with Python 3.12
- ✅ `scrape_and_notify.py` — `py_compile` + **66 unit tests** (v1.3.1 refactor; +6 TestNoPromotionsSkip)
- ✅ `.github/workflows/hotel-monitor.yml` — valid YAML, 3 jobs with scoped permissions (T11.4: 無需變更)
- ✅ T9.1.1 / 9.1.2 / 9.1.3 implemented (`_is_page_stale`, `PROMO_STALE_DAYS=180`, `DYNAMIC_CLASS_PATTERN` decompose)
- ✅ T9.3.x / 9.4.x / 9.5.x implemented (date regex, whitelist, parallel scrape, eval set — retained)
- ✅ T9.6.x implemented (Discord retry, JSON logger, promo diff, scoped permissions, DRY_RUN — retained)
- ✅ T10.1–T10.8 implemented (BASE_URL switch, region whitelist, EXCLUDE_KEYWORDS trimmed, detail-page parallel fetch, region-grouped Discord, LLM removed, golden set + tests rewritten)
- ✅ **T11.1–T11.4** implemented (skip Discord when `filtered` empty; `run.no_promotions` event; `run.end.discord_sent` flag; `build_no_packages_message` deleted; 6 new tests)
- ✅ `evaluation/evaluate.py` — **20/20 (100% accuracy)** on new hotel_packages.php golden set
