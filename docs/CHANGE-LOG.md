# CHANGE-LOG.md — Session Summaries

> Format: `.md` | Retention: last 30 sessions / 14 days | Threshold: 15KB (auto-trim)

---

## 2026-06-06 | [T9.2 implementation + T9.1 verification]

- **Scope**: docs/PLAN.md T9.1.x (verify) + T9.2.x (implement)
- **Files modified**:
  - `scrape_and_notify.py` — T9.2.1/2/3: structured LLM output
  - `docs/PLAN.md` — marked T9.1.1, T9.1.2, T9.1.3, T9.2.1, T9.2.2, T9.2.3 as `[x]`
- **Code changes (T9.2)**:
  - **T9.2.1** [ACC-1]: `call_llm()` now uses `response_format={"type":"json_object"}` and returns `{"packages": [...], "excluded_count": int}` dict. JSON parse failures surface as `RuntimeError`.
  - **T9.2.2** [ACC-1]: Removed brittle `count_hotel_packages` regex; `build_discord_message()` now reads `len(llm_data["packages"])`. New `_parse_llm_json()` helper normalizes fields (default `nights=1`, `validity="持續有效"`, `price="請查閱官網"`, etc.) and tolerates malformed responses.
  - **T9.2.3** [ACC-4]: System prompt now mandates JSON output with explicit schema, and includes 4 few-shot examples (2 qualified hotel packages + 2 disqualified: concert, transport-only).
  - New helpers `_render_package_block()` and `_render_packages_markdown()` reconstruct the SCOPE.md §7 Markdown format from JSON. Discord output format is **unchanged** (per AGENTS.md "DO NOT change Discord message structure without updating SCOPE.md §7").
  - `main()` call order preserved: `scrape_all_pages → compute_hash → prefilter → call_llm → post_to_discord` (only the return type of `call_llm` changed).
  - Added `import json` (stdlib only — no new dependencies).
- **T9.1 verification**:
  - Confirmed via `git log` that commit `8113ae7` (2026-06-06) already implemented T9.1.1 (`_is_page_stale` + early-stop in `scrape_all_pages`), T9.1.2 (`PROMO_STALE_DAYS=180` with env override), and T9.1.3 (`DYNAMIC_CLASS_PATTERN` decompose pre-hash). All 3 tasks now marked `[x]` in PLAN.md.
- **Validation**:
  - ✅ `python -m py_compile scrape_and_notify.py`
  - ✅ Smoke test (synthetic JSON input): render output matches SCOPE.md §7 character-for-character (header emoji, per-package block, stats line, footer divider)
  - ✅ Parse fallback test: missing/invalid fields default safely; invalid JSON raises `RuntimeError`
- **Risk**: Medium — LLM models may need 1-2 runs to adapt to JSON-only output. Fallback chain still active; no model parameter changes. Discord format identical to v1.1, so no SCOPE.md §7 update needed.
- **Rollback**: `git revert HEAD` (single-commit revert). Old text-summary `call_llm()` available in `8113ae7~1` and earlier.
- **Note (stale docs)**: `docs/CONTEXT-MAP.md:43-44` still flags T9.1.1/T9.1.2 as outstanding — these warnings are stale and predate commit `8113ae7`. Per protocol, not auto-modifying CONTEXT-MAP; recommend manual refresh in next docs-sync session.

---

## 2026-06-06 | [v1.2 enhancement proposal — scope expansion]

- **Files updated**:
  - `docs/SCOPE.md` — appended §10 (v1.2 增強提案): 3 BUG fixes + 6 EFF + 7 ACC + 6 ROB items
  - `docs/PLAN.md` — appended T9 (增強迭代): 19 traceable tasks across 6 sub-sections
- **Files NOT modified**: existing §1–§9 in SCOPE, T1–T8 in PLAN (preserved per protocol)
- **Traceability**: every SCOPE §10 item mapped to ≥1 PLAN T9 task; cross-ref table included
- **Validation**: ❌ None — all new tasks are `- [ ]` (pending implementation)
- **Risk**: Low — additive only, no existing content altered
- **Rollback**: delete §10 from SCOPE.md and T9 from PLAN.md
- **Note**: T9.1.1/9.1.2/9.1.3 (BUG fixes) are 🔴 必修 — recommended for next sprint

---

## 2026-06-06 | [Project audit + memory sync]

- **Files created**:
  - `AGENTS.md` (project root) — workflow rules, AI directives, token budgets
  - `docs/ARCHITECTURE.md` — system topology, data model, business rules
  - `docs/CONTEXT-MAP.md` — file navigation index
  - `docs/CHANGE-LOG.md` — this file
  - `docs/DB-SCHEMA.md` — N/A marker (project has no DB)
- **Files preserved (upstream)**: `docs/SCOPE.md`, `docs/PLAN.md` — not modified
- **Files NOT created (per protocol)**:
  - `docs/DESIGN.md` — script project, no UI; input-only file excluded
- **Findings logged for follow-up** (do NOT auto-fix in this session):
  - 🔴 `scrape_and_notify.py:247` — FR-1.3 early-stop not implemented; scrapes all 3 pages regardless
  - 🟡 `scrape_and_notify.py:66` — `PROMO_STALE_DAYS=60` mismatches `SCOPE.md` FR-6.4 (180 days)
  - 🟡 Hash covers raw page text including ads/counters — false-positive change triggers LLM
  - 🟢 Date regex coverage gaps: 「即日起」+ no-year end date, slash-separated dates
- **Validation**: ✅ All created files are well-formed Markdown; totals <50KB cap
- **Risk**: Low — additive docs only, no source modification
- **Rollback**: Delete the 5 created files

---

## 2026-06-06 | [Enhancement recommendations — informational only]

- **Files**: None modified (analysis only)
- **Topics covered**:
  - **Efficiency**: parallel page scraping, content normalization, JSON mode, model parallelism, per-page hash
  - **Accuracy**: few-shot prompting, JSON schema output, reverse keyword whitelist, self-consistency
  - **Robustness**: Discord retry, structured logging, per-page hash diff, evaluation set
- **Validation**: N/A (no code changes)
- **Risk**: Low
- **Rollback**: N/A
- **Note**: Awaiting user decision on which enhancements to implement before any source edits
