# 環島中港通 酒店套票監察系統

每日自動監察 [環島中港通酒店套票頁面](https://www.tilchinalink.com/hotel_packages.php?lang=tc)，篩選 深圳 / 廣州 / 中山 / 珠海 4 個地區之酒店套票（住宿 + 車費 + 自助餐/早餐），並透過 Discord Webhook 發送繁體中文摘要通知。

## 運作流程

1. **抓取** — 以 HTTP GET 抓取 `hotel_packages.php?lang=tc`（網站已策展為酒店套票專屬頁）
2. **變更偵測** — 比對 SHA-256 雜湊值，若頁面無變更則跳過後續所有步驟（0 次 HTTP 調用）
3. **地區過濾** — 僅保留 INCLUDE_REGIONS（深圳/廣州/中山/珠海）之卡片
4. **程序化預篩選** — 排除過期優惠（>180 天未更新）及滑雪套票（`滑雪`/`雪場` 關鍵詞）
5. **並行詳情頁抓取** — `ThreadPoolExecutor(max_workers=4)` 並行抓取每張卡片對應的 `promotions.php?id=XXX`，提取餐飲/交通/晚數/房型/發布日期
6. **Discord 通知** — 按地區分組，發送繁體中文摘要至指定 Discord 頻道

## Discord 訊息範例

```
🏨 環島中港通 深圳 / 中山 / 珠海 酒店套票快訊 | 17/06/2026

━━ 深圳（8 個套票）━━

🏨 **寶安登喜路國際大酒店套票**
💰 價格：HK$365 起/位
🛏️ 住宿：1 晚，標準房
🍽️ 餐飲：自助早餐
🚍 交通：直通巴士
📅 發布：2026-05-12
🔗 優惠詳情：https://www.tilchinalink.com/promotions.php?id=85&lang=tc

🏨 **深圳同泰萬怡酒店套票**
…

✅ 共 11 個酒店套票 | 🚫 已排除 11 個其他優惠
━━━━━━━━━━━━━━━━━━━━━━
📊 掃描：1 頁 | 卡片：22 | 地區排除：7 | 其他排除：4 | 最終保留：11
━━━━━━━━━━━━━━━━━━━━━━
🔗 查閱所有套票 → https://www.tilchinalink.com/hotel_packages.php?lang=tc
```

## 技術棧

- **排程與執行：** GitHub Actions（每日 09:00 HKT / 01:00 UTC）
- **語言：** Python 3.12
- **通知：** Discord Incoming Webhook
- **費用：** $0/月（v1.3 起完全無 LLM API 成本）

## 文件結構

```
chinalink-hotel-monitor/
├── .github/
│   └── workflows/
│       └── hotel-monitor.yml
├── project-documents/
│   ├── Requirements.md
│   └── ImplementationPlan.md
├── docs/
│   ├── SCOPE.md        # §11 = v1.3 變更說明
│   ├── PLAN.md         # T10 = v1.3 任務清單
│   └── ...
├── evaluation/
│   ├── evaluate.py
│   └── golden_set.jsonl
├── tests/
│   └── test_t9.py
├── scrape_and_notify.py
├── requirements.txt
├── last_hash.txt
└── README.md
```

## 設定步驟

### 1. GitHub Secrets

前往 **Settings → Secrets and variables → Actions**，新增：

| Secret | 說明 |
|---|---|
| `DISCORD_WEBHOOK_URL` | Discord Incoming Webhook URL（**v1.3 唯一必需的 secret**） |

> ℹ️ `OPENROUTER_API_KEY` 在 v1.3 不再使用 — 可從 Secrets 移除（保留亦無害）。

### 2. GitHub Variables（選用）

在同一頁面的 **Variables** 標籤，新增以下 Variables（皆已有預設值可省略）：

| Variable | 預設值 | 說明 |
|---|---|---|
| `PROMO_STALE_DAYS` | `180` | 優惠過期閾值（天） |
| `DISCORD_RETRY_MAX` | `3` | Discord 重試次數 |
| `DISCORD_RETRY_BACKOFF` | `2` | Discord 重試退避基礎 |
| `DETAIL_FETCH_TIMEOUT` | `15` | 詳情頁抓取超時（秒） |
| `DETAIL_FETCH_WORKERS` | `4` | 詳情頁並行抓取 worker 數 |
| `DRY_RUN` | （空） | 設為 `true` / `1` / `yes` 啟用測試模式 |

### 3. 手動測試

前往 **Actions → 每日酒店套票監察 — 環島中港通 → Run workflow**。

## 每日行為

| 情況 | LLM 調用 | Discord 訊息 |
|---|---|---|
| 頁面已更新 + 有保留卡片 | 否（v1.3） | 按地區分組的繁體中文套票摘要 |
| 頁面已更新 + 無保留卡片 | 否（v1.3） | 「今日『指定地區』無酒店套票」 |
| 頁面無變更 | 否 | 「今日頁面無更新」一行通知 |
| 抓取或 Discord 發送失敗 | — | 錯誤警報 |

---

*版本 1.3 | 17 June 2026 | 環島中港通酒店套票監察系統 | Henry Fok / Legato Technologies Limited*
