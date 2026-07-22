# CHANGE-LOG.md — Session Summaries

> Format: `.md` | Retention: last 30 sessions / 14 days | Threshold: 15KB (auto-trim)
> Archive: `docs/archive/CHANGE-ARCHIVE-YYYY-QN.md` (trimmed 2026-07-22 — moved 8 sessions from Q2 2026 to `CHANGE-ARCHIVE-2026-Q2.md` per retention policy)

---

## 2026-07-22 | [v1.3.2 — Skip Discord when page has no changes]

- **Scope**: `docs/SCOPE.md` §7 + `docs/PLAN.md` T12 + `scrape_and_notify.py` (main() 早退分支) + `tests/test_t9.py` (新增 `TestNoChangeSkip`) + `docs/ARCHITECTURE.md` (no-show tolerance) + `README.md` (每日行為表) + `docs/CONTEXT-MAP.md` (line numbers + T12 marker)
- **Trigger**: v1.3.1 已對「頁面有更新但無保留卡片」路徑靜默化，但「頁面無更新」分支仍每日發送 `ℹ️ 環島中港通 酒店套票 — 今日頁面無更新（…）` 一行確認通知 — 用戶今日回報接收到了該訊息，要求完全靜默
- **Key changes**:
  - `main()` 在 `current_hash == load_last_hash()` 早退分支中刪除 `post_to_discord()` + `build_stats_footer()` 內聯調用 — 改為僅 emit `run.no_change` 結構化事件（含 `pages` / `total_promos`）然後 `return`
  - 移除「無更新」分支的 Discord 訊息構建代碼（~14 行 dead code）
  - 不執行 `save_hash()` / `save_last_promos()`（因為雜湊值本就未變更）
  - `run.no_change` 事件新增 `total_promos` 欄位（與 `run.no_promotions` 對齊觀測維度）
  - 6 個新測試 (`TestNoChangeSkip`) 覆蓋：skip Discord / `run.no_change` log event / 跳過 `prefilter` / 不混淆 `run.no_promotions` / 即使有卡片仍靜默 / 雜湊不同時走完整流程（回歸）
- **Validation**:
  - ✅ `python -m py_compile scrape_and_notify.py`
  - ✅ `python -m unittest tests.test_t9` — **72/72 pass** (66 pre-existing + 6 new)
  - ✅ `python -m evaluation.evaluate` — **20/20 (100%)**
- **Workflow**: `.github/workflows/hotel-monitor.yml` **未變更** — monitor job 在「無更新」分支直接 `return`，行為與 T11 「無保留卡片」分支一致
- **Risk**: Low — surgical 行為變更；`main()` 調用順序保留 (T10.7.5)；僅 Discord 通知路徑受影響
- **Rollback**: `git revert HEAD` — 恢復 `main()` 早退分支的 `post_to_discord()` + `build_stats_footer()` 調用 + 6 個新測試
- **Note**: 與 v1.3.1 設計理念對稱 — Discord 頻道僅承載「實質新套票」訊號；「無更新」與「無保留卡片」路徑均交由結構化日誌 (`run.no_change` / `run.no_promotions`) 觀測即可

---

## 2026-07-21 | [v1.3.1 — Skip Discord when no promotions match]

- **Scope**: `docs/SCOPE.md` §7 + `docs/PLAN.md` T11 + `scrape_and_notify.py` (main() + 删除 `build_no_packages_message` + 简化 `build_discord_message`) + `tests/test_t9.py` (新增 `TestNoPromotionsSkip`) + `docs/ARCHITECTURE.md` (no-show tolerance) + `README.md` (每日行为表) + `docs/CONTEXT-MAP.md` (line numbers + T11 验证)
- **Trigger**: User observed v1.3 在页面已抓取但無保留卡片时仍发送「🔍 環島中港通 酒店套票」一行空通知 — 多日累积造成 Discord 频道噪音
- **Key changes**:
  - `main()` 在 `filtered` 为空时跳过 `post_to_discord()` — emit `run.no_promotions` 事件 + `run.end.discord_sent=False` + 仍更新 `last_hash.txt` + `last_promos.json`
  - 删除 `build_no_packages_message()` (1003 bytes 死代码)
  - 简化 `build_discord_message()` — 移除空列表分支；文件字符串新增「调用者责任」说明
  - 全部行尾 `\r\r\n` → `\n` (file size: 37506 → 35532 bytes — 同步修正了上次提交遗留的混合行尾)
  - 6 个新测试 (`TestNoPromotionsSkip`) 覆盖：skip Discord / log event / `discord_sent=False` / 全过滤 / 状态文件更新 / 有保留时仍发送（回归）
- **Validation**:
  - ✅ `python -m py_compile scrape_and_notify.py`
  - ✅ `python -m unittest tests.test_t9` — **66/66 pass** (60 pre-existing + 6 new)
  - ✅ `python -m evaluation.evaluate` — **20/20 (100%)**
- **Workflow**: `.github/workflows/hotel-monitor.yml` **未变更** — monitor job 退出码不再依赖 Discord 发送（跳过路径直接 return 0）
- **Risk**: Low — surgical 行为变更；`main()` 调用顺序保留 (T10.7.5)；仅 Discord 通知路径受影响
- **Rollback**: `git revert HEAD` — 恢复 `build_no_packages_message` + 旧 `main()` 流程 + 6 个新测试
- **Note**: 用户在 v1.3.1 实际关注点为「是否有新套票可买」而非「今日无套票」的日常确认 — 反映了 Discord 频道的信号/噪音比优化考量
