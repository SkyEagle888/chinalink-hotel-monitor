# CHANGE-LOG.md — Session Summaries

> Format: `.md` | Retention: last 30 sessions / 14 days | Threshold: 15KB (auto-trim)

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
