# 環島中港通 酒店套票監察系統

每日自動監察 [環島中港通優惠頁面](https://www.tilchinalink.com/promotions.php)，篩選符合條件的酒店套票（住宿 + 車費 + 自助餐/早餐），並透過 Discord Webhook 發送繁體中文摘要通知。

## 運作流程

1. **抓取** — 以 HTTP GET 抓取優惠頁面第 1–3 頁（繁體中文版）
2. **變更偵測** — 比對 SHA-256 雜湊值，若頁面無變更則跳過後續所有步驟（0 次 API 調用）
3. **程序化預篩選** — 排除已過期優惠（日期解析）及明顯非酒店類型（關鍵詞匹配），若無候選則跳過 LLM
4. **LLM 分類摘要** — 僅將預篩選後的候選優惠發送至 OpenRouter 免費模型，精準篩選酒店套票
5. **Discord 通知** — 發送繁體中文摘要至指定 Discord 頻道

## Discord 訊息範例

```
🏨 環島中港通 酒店套票快訊 | 27/04/2026

🏨 **【套票名稱】**
📅 有效期：【日期】
💰 價格：【價格】
🍽️ 餐飲：【自助餐 / 早餐詳情】
🛏️ 住宿：【晚數 + 房型】
📲 訂票：【渠道】
📝 備注：【限制或亮點】
🔗 優惠詳情：https://www.tilchinalink.com/promotions.php?id=XXX

✅ 找到 1 個酒店套票 | 🚫 已排除 6 個非酒店優惠
━━━━━━━━━━━━━━━━━━━━━━
🔗 查閱所有優惠 → https://www.tilchinalink.com/promotions.php
```

## 技術棧

- **排程與執行：** GitHub Actions（每日 09:00 HKT / 01:00 UTC）
- **語言：** Python 3.12
- **LLM：** OpenRouter 免費模型（模型備用鏈：Qwen3-Next 80B → GLM-4.5-Air → Llama 3.3 70B）
- **通知：** Discord Incoming Webhook
- **費用：** $0/月

## 文件結構

```
chinalink-hotel-monitor/
├── .github/
│   └── workflows/
│       └── hotel-monitor.yml
├── project-documents/
│   ├── Requirements.md
│   └── ImplementationPlan.md
├── scrape_and_notify.py
├── requirements.txt
├── last_hash.txt
└── README.md
```

## 設定步驟

### 1. GitHub Secrets

前往 **Settings → Secrets and variables → Actions**，新增以下 Secrets：

| Secret | 說明 |
|---|---|
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) API 金鑰（免費帳戶） |
| `DISCORD_WEBHOOK_URL` | Discord Incoming Webhook URL |

### 2. GitHub Variables

在同一頁面的 **Variables** 標籤，新增以下 Variables：

| Variable | 預設值 |
|---|---|
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` |
| `OPENROUTER_MODEL_PRIMARY` | `qwen/qwen3-next-80b:free` |
| `OPENROUTER_MODEL_SECONDARY` | `z-ai/glm-4.5-air:free` |
| `OPENROUTER_MODEL_TERTIARY` | `meta-llama/llama-3.3-70b-instruct:free` |

### 3. 手動測試

前往 **Actions → 每日酒店套票監察 — 環島中港通 → Run workflow**。

## 每日行為

| 情況 | LLM 調用 | Discord 訊息 |
|---|---|---|
| 頁面已更新 + 預篩選後有候選 + 找到酒店套票 | 是 | 繁體中文套票摘要（含優惠 URL） |
| 頁面已更新 + 預篩選後有候選 + 無酒店套票 | 是 | 「今日無酒店套票」通知 |
| 頁面已更新 + 預篩選後無候選 | 否 | 「今日無酒店套票」通知（程序化生成） |
| 頁面無變更 | 否 | 「今日頁面無更新」一行通知 |
| 抓取或 LLM 失敗 | — | 錯誤警報 |

---

*Henry Fok / Legato Technologies Limited | 2026*
