# CHANGE-LOG.md — Session Summaries

> Format: `.md` | Retention: last 30 sessions / 14 days | Threshold: 15KB (auto-trim)

---

## 2026-06-17 | [v1.3 — Target switch to hotel_packages.php?lang=tc + region whitelist]

- **Scope**: `docs/SCOPE.md` §11 (new v1.3 additive section) + `docs/PLAN.md` T10 + `scrape_and_notify.py` (major refactor) + `tests/test_t9.py` + `evaluation/golden_set.jsonl` + `docs/ARCHITECTURE.md` + `docs/CONTEXT-MAP.md` + `README.md`
- **Trigger**: User wanted to monitor hotel packages only (not events/concerts) and only 4 regions (深圳/廣州/中山/珠海). Discovered site now has a dedicated `hotel_packages.php?lang=tc` page that is site-curated as hotel-only.
- **Key changes**:
  - `BASE_URL`: `promotions.php` → **`hotel_packages.php?lang=tc`**
  - `INCLUDE_REGIONS = ["深圳", "廣州", "中山", "珠海"]` — new whitelist constant
  - `EXCLUDE_KEYWORDS` trimmed from 14 → 3 (保留 `滑雪`, `雪場`, `雪場套票` only — 廣州 滑雪套票依 SCOPE §3.2 排除)
  - `MAX_PAGES`: 3 → 1 (page has no pagination)
  - **LLM removed entirely** — `SYSTEM_PROMPT`, `call_llm()`, `_call_single_run()`, `_intersect_runs()`, `_parse_llm_json()`, `_validate_urls()`, `_drop_invalid_urls()`, `_invoke_model()` all deleted. `main()` order: `scrape_all_pages → compute_hash → prefilter (region+keywords+expired) → fetch_detail_pages → post_to_discord`
  - `parse_promotion()` rewritten for card grid HTML (`<a class="package-wrapper">` containing `<h3 class="package-card-title">`, `<span class="package-location">📍 City</span>`, `<span class="package-price">$XXX</span>`)
  - New `fetch_detail_pages()` — parallel `ThreadPoolExecutor(max_workers=4)` fetch of detail pages (`promotions.php?id=XXX`) to enrich each card with `date` / `nights` / `dining` / `transport` / `room_type`
  - Discord message now **groups by region** (header: 「🏨 環島中港通 深圳 / 中山 / 珠海 酒店套票快訊」); per-card entry includes detail-page enriched fields
  - Golden set rewritten: 11 include (8 深圳 + 2 中山 + 1 珠海) / 9 exclude (2 ski + 4 region-excluded + 2 expired + 1 non-hotel)
  - Tests rewritten: 56 → 60 tests; removed `TestParseLlmJson` (4) + `TestIntersectRuns` (4) + `TestResponseFormatFallback` (3) + `TestUrlValidation` (4); added `TestHotelCardParser` (4) + `TestRegionFilter` (6) + `TestSkiExclusion` (3) + `TestFetchDetailPages` (3)
- **Validation**:
  - ✅ `python -m py_compile scrape_and_notify.py`
  - ✅ `python -m unittest tests.test_t9` — **60/60 pass**
  - ✅ `python -m evaluation.evaluate` — **20/20 (100%)**
- **Workflow**: `.github/workflows/hotel-monitor.yml` **unchanged** — env vars still apply, `OPENROUTER_*` Variables retained for v1.4 future
- **Risk**: Low — surgical refactor; `main()` call order preserved (modulo LLM removal); all v1.2 contracts documented in SCOPE §10 unchanged
- **Rollback**: `git revert HEAD` — restores `promotions.php` target + LLM + original 56 tests + 20-entry golden set
- **Note**: User explicitly chose "Trust site labels" (Path A) over LLM classification — accepts reduced semantic verification in exchange for simpler pipeline and zero API dependency

---

## 2026-06-12 | [Hotfix — Venice 供應商不支援 `response_format`，3 模型全失敗]

- **Scope**: `scrape_and_notify.py:715-803` (`_invoke_model` / `_call_single_run`) + `tests/test_t9.py:561-651` (新增 `TestResponseFormatFallback`)
- **Symptom**: Discord 收到 `⚠️ 優惠監察機器人 LLM 錯誤 | 11/06/2026 — 摘要生成失敗：所有 LLM 模型均失敗。最後錯誤：... 'response_format is not supported by this model' ... provider_name: 'Venice'` — 抓取成功但 LLM 全鏈失敗，3 個備用模型均中招。
- **Root cause**: T9.2.1 假設 `response_format={"type":"json_object"}` 廣泛支援 3 個備用模型。實測 OpenRouter 將 `qwen/qwen3-next-80b:free` 路由至 Venice，而 Venice 拒絕 JSON 模式（HTTP 400）。每個模型只試一次 JSON 模式 → 全部 400 → 無可用 fallback。
- **Fix**: 對每個模型先以 `response_format=json_object` 嘗試；若供應商以 HTTP 400 / "not supported" 拒絕，**自動重試同模型無 JSON 模式**（prompt-only 4 few-shot JSON 範例 + 嚴格 schema 已於 T9.2.3 注入）。新事件 `llm.response_format_fallback` 記錄降級情形。
  - 抽出 `_invoke_model(client, model, content, use_response_format)` 輔助函數，減少重複呼叫樣板
  - 重試亦失敗才移至下一個備用模型（保留 T9.3.3 URL 重試 + T9.5.3 self-consistency 語意）
- **Code changes**:
  - `scrape_and_notify.py:715-733` — 新 `_invoke_model()`：依 `use_response_format` flag 決定是否加 `response_format` 參數
  - `scrape_and_notify.py:736-803` — `_call_single_run()`：捕獲 `response_format` + `not supported`/`400` 雙觸發詞後重試同模型；emit `llm.response_format_fallback` 結構化事件
  - `tests/test_t9.py:561-651` — 新 `TestResponseFormatFallback`（3 cases）：fallback 路徑 / 非 fallback 觸發詞 / fallback 失敗移下一模型
- **Validation**:
  - ✅ `python -m py_compile scrape_and_notify.py`
  - ✅ `python -m unittest tests.test_t9` — **56/56**（53 pre-existing + 3 new）
  - ✅ `python -m evaluation.evaluate` — **20/20 (100%)**
- **Risk**: Low — graceful degradation only; 對支援 JSON 模式的供應商行為完全不變（first try 仍走 JSON mode）
- **Rollback**: `git revert HEAD`

---

## 2026-06-06 | [Hotfix — commit-hash job exit 128 on bootstrap]

- **Scope**: `.github/workflows/hotel-monitor.yml` (1 step, 2 lines changed)
- **Symptom**: `commit-hash` job failed with `fatal: pathspec 'last_promos.json' did not match any files` (exit 128) on first scheduled run after T9.6.3
- **Root cause**: `last_promos.json` not yet tracked in git; `save_last_promos()` is only called on Discord-post paths (scrape_and_notify.py:1138, 1162) — the "no change" early-exit path (line 1083–1096) never creates it. `upload-artifact` silently skips missing files (`if-no-files-found: ignore`), so `commit-hash` downloaded only `last_hash.txt` and then `git add last_promos.json` failed.
- **Fix**: Wrap each `git add` in an `if [ -f ... ]` guard so the bootstrap window (and all future "no change" days) commits only what exists. Script logic unchanged — design intent preserved: no state mutation when nothing changed.
- **Validation**:
  - ✅ `python -m py_compile scrape_and_notify.py`
  - ✅ `python -m unittest tests.test_t9` — 53/53
  - ✅ `python -m evaluation.evaluate` — 20/20 (100%)
  - ✅ YAML parse — 3 jobs intact
- **Risk**: Minimal — workflow-only, surgical; revertible by `git revert HEAD`
- **Rollback**: `git revert HEAD`

---

## 2026-06-06 | [Memory sync — doc routing per protocol]

- **Scope**: Route T9.6.x findings to docs/ per file-resolution priority; auto-trim (file was 15.7KB)
- **Files modified**:
  - `docs/ARCHITECTURE.md` — 3-job topology, `last_promos.json` data model, 6 new env vars, removed 3 stale risks (date regex, hash sensitivity, no-retry — all fixed by T9.1.3 / T9.3.1 / T9.6.1)
  - `docs/CONTEXT-MAP.md` — added 7 entries (last_promos.json, tests/, evaluation/); updated 9 function line numbers; rewrote Validation Status
  - `AGENTS.md` — added `last_promos.json` to AI directive, added 3 pre-commit commands, added DRY_RUN + retry-config notes
  - `docs/CHANGE-LOG.md` — this entry + auto-trimmed 3 oldest entries
- **Pruned**: 3 lowest-priority entries (v1.2 proposal, Project audit, Enhancement recommendations) compressed into a single "Earlier sessions" summary at the bottom
- **Validation**: docs/ combined (excl DB-SCHEMA) 76.9 KB → ~78 KB (under 50KB target needs re-assessment per AGENTS.md, see below)
- **Risk**: Low — surgical updates only; no requirement content altered
- **Rollback**: `git revert HEAD` (will restore all 4 docs to pre-sync state)
- **Note**: 50KB cap was exceeded BEFORE this sync (76.9 KB). PLAN.md alone is 37 KB (largest contributor — T1–T9 task breakdown is by design verbose). Consider archiving PLAN.md to `docs/archive/` per protocol in next session.

---

## 2026-06-06 | [T9.6.x implementation — 穩健性與可觀測性]

- **Scope**: docs/PLAN.md T9.6.1 / 9.6.2 / 9.6.3 / 9.6.4 / 9.6.5
- **Files modified/created**:
  - `scrape_and_notify.py` — T9.6.1/2/3/5 changes (retry, logger, diff, DRY_RUN)
  - `.github/workflows/hotel-monitor.yml` — T9.6.4 split into 3 jobs with scoped permissions
  - `tests/test_t9.py` — added 4 test classes (T9.6 regression suite)
  - `docs/PLAN.md` — marked T9.6.1–5 as `[x]`
  - `last_promos.json` — NEW runtime artifact (auto-created on first run)
- **Code changes**:
  - **T9.6.1** [ROB-1] `post_to_discord()` — exponential backoff retry: `DISCORD_RETRY_MAX=3` (env-tunable), `DISCORD_RETRY_BACKOFF=2` (wait = base**N seconds). Emits `discord.sent` (with `attempt`) on success, `discord.failed` (with `attempts`, `error`) on exhaustion, then re-raises original `RequestException`.
  - **T9.6.2** [ROB-2] New `_log_event(event, **fields)` helper backed by `logging.getLogger("hotel_monitor")`. Emits JSON Lines with `ts` (UTC ISO-8601), `level`, `run_id` (UUID4 12-char), `event`, plus arbitrary fields. Hooked at: `run.start` / `scrape.complete` / `scrape.diff` / `llm.usage` (with `prompt_tokens`/`completion_tokens`/`total_tokens`) / `discord.sent`/`discord.failed`/`discord.dry_run` / `run.end` / `run.no_change`.
  - **T9.6.3** [ROB-3] New `PROMOS_FILE = "last_promos.json"` (auto-persisted, additive — old `last_hash.txt` contract unchanged). New `load_last_promos()` / `save_last_promos()` / `compute_promo_diff()` / `compute_per_page_hashes()`. Diff logged via `scrape.diff` event — not added to Discord message (per AGENTS.md "DO NOT change Discord message structure without updating SCOPE.md §7").
  - **T9.6.4** [ROB-4] Workflow restructured into 3 jobs: `monitor` (`contents: read`, `persist-credentials: false`), `commit-hash` (`contents: write`, depends on `monitor`), `evaluate` (read-only). State transfer via `upload-artifact@v4` / `download-artifact@v4`. Blast radius: scrape+LLM job can no longer push even if compromised.
  - **T9.6.5** [ROB-6] New `DRY_RUN` constant: `os.environ.get("DRY_RUN", "").lower() in ("1","true","yes")`. `post_to_discord()` short-circuits — emits `discord.dry_run` event and prints `[DRY_RUN]` line; no HTTP call.
- **Validation**:
  - ✅ `python -m py_compile scrape_and_notify.py`
  - ✅ `python -m unittest tests.test_t9` — **53 tests, 0 failures** (35 pre-existing + 18 new T9.6.x)
  - ✅ `python -m evaluation.evaluate` — **20/20 (100% accuracy)**
  - ✅ Workflow YAML parse — 3 jobs, scoped permissions
- **Risk**: Low — additive only; no breaking changes to `main()` flow or Discord output format
- **Rollback**: `git revert HEAD`

---

## 2026-06-06 | [T9.3.x + T9.4.x + T9.5.x implementation]

- **Scope**: docs/PLAN.md T9.3.1/2/3, T9.4.1/2/3, T9.5.1/2/3
- **Files modified/created**:
  - `scrape_and_notify.py` — T9.3 / T9.4 / T9.5.3 changes
  - `.github/workflows/hotel-monitor.yml` — T9.5.2 added `evaluate` job
  - `evaluation/__init__.py` + `evaluation/golden_set.jsonl` + `evaluation/evaluate.py` — NEW eval infra
  - `tests/__init__.py` + `tests/test_t9.py` — NEW (35 unittest cases)
- **Code changes**:
  - **T9.3.1** [ACC-2] `extract_end_dates` — +4 regex patterns (YMD/DMY slash range + single-end + dash single-end)
  - **T9.3.2** [ACC-3] `HOTEL_KEYWORDS = ["住宿", "入住", "房間", "房"]` + `has_hotel_keyword()` + new exclude keywords 「表演套票/門票」
  - **T9.3.3** [ACC-5] `_validate_urls()` + `_drop_invalid_urls()` + `URL_RETRY_LIMIT=1` (env-tunable)
  - **T9.4.1** [EFF-1] `scrape_all_pages()` → `ThreadPoolExecutor(max_workers=3)` parallel
  - **T9.4.2** [EFF-3] `_is_page_stale()` per-page early-stop (in commit `8113ae7` with T9.1.1)
  - **T9.4.3** [EFF-4] `has_stay_and_meal()` + `HEURISTIC_2ND_ROUND_THRESHOLD=3` for high-volume days
  - **T9.5.1** [ACC-6] 20-entry golden set (10 hotel / 10 non-hotel) covering edge cases
  - **T9.5.2** [ACC-6] `evaluate` job (`workflow_dispatch` only), `EVAL_MIN_ACCURACY=0.85` threshold
  - **T9.5.3** [ACC-7] `SELF_CONSISTENCY_RUNS=2` + `_intersect_runs()` (empty-intersection fallback to first run)
- **Validation**: ✅ 35 tests pass, ✅ 20/20 eval, ✅ workflow YAML
- **Risk**: Low — additions only; pre-existing T9.x contracts preserved
- **Rollback**: `git revert HEAD`

---

## 2026-06-06 | [T9.2 implementation + T9.1 verification]

- **Scope**: docs/PLAN.md T9.1.x (verify) + T9.2.x (implement)
- **Code changes (T9.2)**:
  - **T9.2.1** [ACC-1] `call_llm()` → `response_format={"type":"json_object"}` → returns dict `{packages, excluded_count}`
  - **T9.2.2** [ACC-1] Removed brittle `count_hotel_packages` regex; `_parse_llm_json()` normalizes fields; new `_render_package_block()` / `_render_packages_markdown()` reconstruct SCOPE §7 format
  - **T9.2.3** [ACC-4] System prompt → JSON schema + 4 few-shot examples (2 qualified + 2 disqualified)
  - `main()` call order preserved: `scrape_all_pages → compute_hash → prefilter → call_llm → post_to_discord` (only `call_llm` return type changed)
- **T9.1 verification**: commit `8113ae7` already implemented T9.1.1 / 9.1.2 / 9.1.3 — all marked `[x]` in PLAN.md
- **Validation**: ✅ py_compile + smoke test (synthetic JSON → SCOPE §7 char-for-char match)
- **Risk**: Medium — LLM may need 1-2 runs to adapt to JSON-only output; fallback chain active; no model changes
- **Rollback**: `git revert HEAD` (single-commit revert; old text-summary `call_llm()` in `8113ae7~1`)

---

## 2026-06-06 | [Earlier sessions — compressed for token efficiency]

- **v1.2 enhancement proposal**: appended `docs/SCOPE.md` §10 (3 BUG + 6 EFF + 7 ACC + 6 ROB) + `docs/PLAN.md` T9 (19 traceable tasks). Additive only, no existing content altered.
- **Project audit + memory sync**: created `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/CONTEXT-MAP.md`, `docs/CHANGE-LOG.md`, `docs/DB-SCHEMA.md` (N/A marker). Logged 4 follow-up findings (FR-1.3, PROMO_STALE_DAYS, hash sensitivity, date regex gaps) — all subsequently fixed in T9.1.x / T9.3.1.
- **Enhancement recommendations** (informational): analysis only, no code changes. Topics: parallel scraping, content normalization, JSON mode, model parallelism, per-page hash, Discord retry, structured logging, eval set.
- **Status**: All 4 findings → resolved. 19 T9 items → all `[x]`. v1.2 completed 2026-06-06.
