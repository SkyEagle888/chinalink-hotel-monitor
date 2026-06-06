# CONTEXT-MAP.md — File Navigation Index

> Format: `.md` | Last updated: 2026-06-06
> Primary navigation index. Load only files listed here unless task requires broader scan.

## Module Mappings

| Path | Responsibility | Last Modified | Validation |
|---|---|---|---|
| `scrape_and_notify.py` | Entry point: scrape → hash → prefilter → LLM → Discord | 2026-06-06 | ✅ 53 unit tests |
| `.github/workflows/hotel-monitor.yml` | 3-job workflow (monitor / commit-hash / evaluate), scoped permissions | 2026-06-06 | ✅ Valid YAML, 3 jobs |
| `requirements.txt` | Pinned Python deps (3 packages) | 2026-04-27 | ✅ |
| `last_hash.txt` | SHA-256 state for change detection (in-repo) | 2026-04-27 | ✅ 64 hex chars |
| `last_promos.json` | Full promo list for T9.6.3 diff tracking (in-repo) | 2026-06-06 | ✅ auto-managed |
| `README.md` | User-facing setup + behaviour docs | 2026-04-27 | ✅ |
| `AGENTS.md` | Project workflow rules + AI directives | 2026-06-06 | ✅ |
| `tests/test_t9.py` | 53 unittest cases (T9.3/9.4/9.5/9.6 regression suite) | 2026-06-06 | ✅ 53/53 pass |
| `tests/__init__.py` | Package marker for `python -m unittest tests.test_t9` | 2026-06-06 | ✅ |
| `evaluation/evaluate.py` | Golden-set evaluator (20 labeled examples) | 2026-06-06 | ✅ 20/20 (100%) |
| `evaluation/golden_set.jsonl` | 20 labeled examples (10 hotel / 10 non-hotel) | 2026-06-06 | ✅ |
| `evaluation/__init__.py` | Package marker for `python -m evaluation.evaluate` | 2026-06-06 | ✅ |
| `project-documents/Requirements.md` | Source for SCOPE (FR-1 to FR-6, NFRs) | 2026-04-27 | ✅ Mirrored to docs/SCOPE.md |
| `project-documents/ImplementationPlan.md` | Source for PLAN (T1–T8 tasks) | 2026-04-27 | ✅ Mirrored to docs/PLAN.md |
| `docs/SCOPE.md` | Upstream requirements baseline (§1–§9 immutable, §10 v1.2 completed) | 2026-06-06 | ✅ |
| `docs/PLAN.md` | Implementation plan (T1–T9 all `[x]`) | 2026-06-06 | ✅ |
| `docs/ARCHITECTURE.md` | System topology + data model + business rules | 2026-06-06 | ✅ |
| `docs/CHANGE-LOG.md` | Session summaries (rolling 14d, 15KB trim threshold) | 2026-06-06 | ✅ |
| `docs/DB-SCHEMA.md` | N/A marker (no database in project) | 2026-06-06 | ✅ |
| `docs/CONTEXT-MAP.md` | This file | 2026-06-06 | ✅ |
| `docs/DESIGN.md` | **Not applicable** — no UI; skip | — | ⚠️ Absent by design |

## File Responsibilities

- [x] `scrape_and_notify.py:239-292` `_safe_date` / `extract_end_dates` — 7 Chinese date regex patterns (T9.3.1)
- [x] `scrape_and_notify.py:338-369` `parse_promotion` — HTML `<div class="faintivory-background">` → `promo` dict
- [x] `scrape_and_notify.py:379-403` `fetch_page` — single-page HTTP fetch + dynamic-class decompose (T9.1.3)
- [x] `scrape_and_notify.py:405-464` `_is_page_stale` / `scrape_all_pages` — 3-page parallel (T9.1.1 + T9.4.1) with early-stop
- [x] `scrape_and_notify.py:470-573` `is_expired` / `is_obviously_non_hotel` / `has_hotel_keyword` / `has_stay_and_meal` / `prefilter` (T9.3.2 + T9.4.3)
- [x] `scrape_and_notify.py:575-663` `build_llm_content` / `compute_hash` / `load_last_hash` / `save_hash` / `load_last_promos` / `save_last_promos` / `compute_promo_diff` / `compute_per_page_hashes` (T9.6.3)
- [x] `scrape_and_notify.py:665-858` `call_llm` + self-consistency (T9.5.3) + URL retry (T9.3.3) + JSON mode (T9.2.1) + 3-model fallback
- [x] `scrape_and_notify.py:860-1044` `post_to_discord` (T9.6.1 retry + T9.6.5 DRY_RUN) / `build_*_message` / `_render_*` (SCOPE §7 format)
- [x] `scrape_and_notify.py:1046-1158` `main` — orchestration entry point (call order preserved)
- [x] `scrape_and_notify.py:97-110` `_log_event` + `_STRUCT_LOGGER` — T9.6.2 JSON Lines logger

## Validation Status

- ✅ `requirements.txt` — 3 packages, compatible with Python 3.12
- ✅ `scrape_and_notify.py` — `py_compile` + 53 unit tests
- ✅ `.github/workflows/hotel-monitor.yml` — valid YAML, 3 jobs with scoped permissions
- ✅ T9.1.1 / 9.1.2 / 9.1.3 implemented (`_is_page_stale`, `PROMO_STALE_DAYS=180`, `DYNAMIC_CLASS_PATTERN` decompose)
- ✅ T9.3.x / 9.4.x / 9.5.x implemented (date regex, whitelist, parallel scrape, eval set, self-consistency)
- ✅ T9.6.x implemented (Discord retry, JSON logger, promo diff, scoped permissions, DRY_RUN)
- ✅ `evaluation/evaluate.py` — 20/20 golden set (100% accuracy)
