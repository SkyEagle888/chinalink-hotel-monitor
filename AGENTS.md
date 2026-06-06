# AGENTS.md — chinalink-hotel-monitor

> Format: `.md` (always) | Last updated: 2026-06-06

## Workflow Rules
- Daily 09:00 HKT cron (GitHub Actions) + manual trigger via `workflow_dispatch`
- Single Python entry point: `scrape_and_notify.py` (no package, no venv in repo)
- Pre-commit validation: `python -m py_compile scrape_and_notify.py`
- No external state store — only `last_hash.txt` for change detection
- Secrets must NEVER appear in source — use GitHub Secrets/Variables only

## Context Loading Protocol
- At session start, always read docs/CONTEXT-MAP.md before exploring code.
- Use it as the primary navigation index. Load only files referenced there.
- Never load full directories or unrelated modules without explicit mapping.
- Load `docs/SCOPE.md` and `docs/PLAN.md` at session initialization for requirement baseline and phased task alignment.
- If combined file size exceeds 5KB, extract only the active phase, pending tasks, and requirement boundaries relevant to the current `docs/CHANGE-LOG.md` objective.
- Validate implementation output against `docs/PLAN.md` checkbox status before marking `- [x]`.
- Flag requirement deviations or scope drift in `docs/CHANGE-LOG.md` immediately; do not auto-modify upstream references.

## Architecture & Token Control
- No `graphify-out/GRAPH_REPORT.md` exists for this project — skip graphify step.
- Token budget: combined `AGENTS.md` + `docs/ARCHITECTURE.md` + `docs/CONTEXT-MAP.md` + `docs/CHANGE-LOG.md` <50KB.
- `docs/DB-SCHEMA.md` and `docs/DESIGN.md` are exempt from the 50KB cap.

## UI Development Protocol
- No UI in this project (CLI/scheduled script only).
- `docs/DESIGN.md` does not exist and is not required.
- Discord message templates are the de facto output design — documented in `docs/SCOPE.md` §7. Treat as authoritative for notification formatting.

## Token Budgets
- Session total: <300K tokens
- docs/ combined (AGENTS + ARCHITECTURE + CONTEXT-MAP + CHANGE-LOG + PLAN + SCOPE): <50KB
- CHANGE-LOG rotation: 30 sessions / 14 days; auto-trim when >15KB

## AI Directives
- DO NOT modify `last_hash.txt` manually — only the GitHub Actions bot commits.
- DO NOT add new dependencies without explicit approval.
- DO NOT change Discord message structure without updating `docs/SCOPE.md` §7.
- Honour `EXCLUDE_KEYWORDS` and `MODELS` lists as source of truth for filter logic and LLM fallback chain.
- When refactoring `scrape_and_notify.py`, preserve the `main()` call order: `scrape_all_pages → compute_hash → prefilter → call_llm → post_to_discord`.
