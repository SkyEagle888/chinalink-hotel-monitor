"""
環島中港通 — 每日酒店套票監察系統
抓取 promotions.php（繁體中文版），程序化預篩選以最小化 LLM 用量，
透過 OpenRouter LLM 生成繁體中文摘要，並發送至 Discord Webhook。
"""

import hashlib
import os
import datetime
import time
import re
import requests
from bs4 import BeautifulSoup, Tag
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = "https://www.tilchinalink.com/promotions.php"
MAX_PAGES = 3
HASH_FILE = "last_hash.txt"
TODAY = datetime.date.today()
TODAY_CN = TODAY.strftime("%Y年%m月%d日")
TODAY_SHORT = TODAY.strftime("%d/%m/%Y")

API_KEY = os.environ["OPENROUTER_API_KEY"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
BASE_URL_API = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

MODELS = [
    os.environ.get(
        "OPENROUTER_MODEL_PRIMARY",
        "qwen/qwen3-next-80b:free",
    ),
    os.environ.get(
        "OPENROUTER_MODEL_SECONDARY",
        "z-ai/glm-4.5-air:free",
    ),
    os.environ.get(
        "OPENROUTER_MODEL_TERTIARY",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
]

EXCLUDE_KEYWORDS = [
    "演唱會", "音樂會", "音樂節",
    "主題公園", "雪場", "遊樂場",
    "買去程送回程", "車票半價",
    "充值優惠", "充值獎賞", "消費券", "現金回贈",
    "新增站點", "站點限定",
    "行李托運",
]

MAX_LLM_CHARS = 12000
PROMO_STALE_DAYS = 60

SYSTEM_PROMPT = f"""你是一位專為香港用戶服務的旅遊套票分析師。
今天的日期是 {TODAY_CN}。

你正在閱讀環島中港通的優惠頁面。
環島中港通是一間跨境客運公司，提供香港、澳門及中國大陸之間的客車及豪華轎車服務。

以下優惠已經過程序化預篩選（已排除已過期及明顯非酒店類型的優惠）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
你唯一的任務：識別並摘要「酒店套票」。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

合資格「酒店套票」必須同時包含以下三項：
  1. 酒店住宿（1晚或以上的實際入住）
  2. 巴士／客車／豪華轎車交通（任何方向）
  3. 自助餐或早餐（至少一項）

嚴格排除 — 如優惠主要屬於以下類型，請完全略過：
  ✗ 演唱會、表演或音樂節套票
  ✗ 主題公園、雪場或遊樂場套票
  ✗ 觀光遊覽或導遊套票
  ✗ 純車費優惠（酒店名稱僅為上落車地點，並無實際入住）
  ✗ 充值積分、現金回贈或優惠券
  ✗ 新路線或新站點開通優惠（酒店僅為登車站點）
  ✗ 售票中心折扣券

指示：
1. 掃描每個優惠。
2. 不符合酒店套票定義 → 完全略過，不作任何提及。
3. 符合 → 檢查截至 {TODAY_CN} 是否仍然有效。
   - 已過期 → 靜默略過。
   - 仍有效或無結束日期 → 輸出完整詳情。
4. 對每個有效的合資格酒店套票，輸出以下格式：

🏨 **{{套票名稱}}**
📅 有效期：{{有效日期，若無結束日期則填「持續有效」}}
💰 價格：{{每位價格或套票價，若不明確則填「請查閱官網」}}
🍽️ 餐飲：{{自助餐或早餐詳情}}
🛏️ 住宿：{{晚數}}晚，{{房型（如有說明）}}
📲 訂票：{{訂票渠道：微信小程式 / 支付寶 / 售票中心等}}
📝 備注：{{主要限制或亮點，最多一句}}
🔗 優惠詳情：{{此優惠的個別 URL}}

5. 每個套票區塊之間空一行。
6. 所有輸出區塊後，輸出一行統計：
   「✅ 找到 N 個酒店套票 | 🚫 已排除 M 個非酒店優惠」
7. 若無合資格有效套票，輸出：
   「🔍 今日無酒店套票。已排除 M 個其他優惠。」
8. 每個區塊不超過 120 字。
9. **所有輸出使用繁體中文。**
10. **不要輸出交通時間表、班次或路線詳情。**
11. 不要在格式以外添加任何說明或前言。
"""


# ─────────────────────────────────────────────────────────────────────────────
# 日期解析
# ─────────────────────────────────────────────────────────────────────────────

def _safe_date(year: int, month: int, day: int) -> datetime.date | None:
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def extract_end_dates(text: str, ref_year: int) -> list[datetime.date]:
    """從優惠內容提取所有結束日期。"""
    dates: list[datetime.date] = []

    for m in re.finditer(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日"
        r"\s*[至到\–\-~]\s*"
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        text,
    ):
        d = _safe_date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        if d:
            dates.append(d)

    for m in re.finditer(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日"
        r"\s*[至到\–\-~]\s*"
        r"(\d{1,2})月(\d{1,2})日"
        r"(?!\s*[至到]|年)",
        text,
    ):
        start_month = int(m.group(2))
        end_month = int(m.group(4))
        end_day = int(m.group(5))
        year = ref_year if end_month >= start_month else ref_year + 1
        d = _safe_date(year, end_month, end_day)
        if d:
            dates.append(d)

    for m in re.finditer(
        r"[至到]\s*(\d{4})年(\d{1,2})月(\d{1,2})日", text
    ):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            dates.append(d)

    return dates


# ─────────────────────────────────────────────────────────────────────────────
# 抓取
# ─────────────────────────────────────────────────────────────────────────────

def parse_promotion(div: Tag) -> dict | None:
    """從 HTML 容器提取單個優惠的結構化資料。"""
    title = ""
    url = ""
    date_str = ""
    content = ""

    h4 = div.find("h4")
    if not h4:
        return None

    a = h4.find("a", href=True)
    if a:
        title = a.get_text(strip=True)
        href = a["href"]
        if href and not href.startswith("http"):
            href = f"https://www.tilchinalink.com/{href}"
        url = href

    title_parent = h4.parent
    if title_parent:
        parent_text = title_parent.get_text(strip=True)
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", parent_text)
        if date_match:
            date_str = date_match.group()

    content_span = div.find("span", class_="d-block")
    if content_span:
        content = content_span.get_text(separator=" ", strip=True)

    if not title:
        return None

    return {
        "title": title,
        "date": date_str,
        "content": content,
        "url": url,
    }


def fetch_page(page_num: int) -> tuple[str, list[dict]]:
    """抓取單頁，回傳 (raw_text, promotions_list)。"""
    url = BASE_URL if page_num == 1 else f"{BASE_URL}?page={page_num}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    promotions = []
    for div in soup.find_all("div", class_="faintivory-background"):
        promo = parse_promotion(div)
        if promo:
            promotions.append(promo)

    for unwanted in soup(
        ["nav", "footer", "script", "style", "img", "svg"]
    ):
        unwanted.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return text, promotions


def scrape_all_pages() -> tuple[str, list[dict]]:
    """抓取第 1–MAX_PAGES 頁。"""
    all_text: list[str] = []
    all_promotions: list[dict] = []

    for i in range(1, MAX_PAGES + 1):
        try:
            text, promos = fetch_page(i)
            all_text.append(f"=== 優惠頁面 {i} ===\n{text}")
            all_promotions.extend(promos)
            time.sleep(1.5)
        except requests.RequestException as e:
            if i == 1:
                raise
            print(f"[WARN] 第 {i} 頁抓取失敗：{e}")

    combined_text = "\n\n".join(all_text)
    return combined_text, all_promotions


# ─────────────────────────────────────────────────────────────────────────────
# 程序化預篩選
# ─────────────────────────────────────────────────────────────────────────────

def is_expired(promo: dict) -> bool:
    """根據發布日期及內容結束日期判斷是否已過期。

    規則：
    1. 若內容中有明確結束日期 → 以該日期判斷
    2. 若無明確結束日期 → 發布日期超過 PROMO_STALE_DAYS 天即視為過期
    """
    date_str = promo.get("date", "")
    if not date_str:
        return False

    try:
        publish_date = datetime.datetime.strptime(
            date_str, "%Y-%m-%d"
        ).date()
    except ValueError:
        return False

    end_dates = extract_end_dates(
        promo.get("content", ""), publish_date.year
    )

    if end_dates:
        latest_end = max(end_dates)
        if latest_end < TODAY:
            return True
    else:
        if (TODAY - publish_date).days > PROMO_STALE_DAYS:
            return True

    return False


def is_obviously_non_hotel(promo: dict) -> bool:
    """關鍵詞匹配排除明顯非酒店套票。"""
    combined = promo.get("title", "") + " " + promo.get("content", "")
    for kw in EXCLUDE_KEYWORDS:
        if kw in combined:
            return True
    return False


def prefilter(
    promotions: list[dict],
) -> tuple[list[dict], int]:
    """程序化預篩選。回傳 (filtered_list, excluded_count)。"""
    filtered: list[dict] = []
    excluded = 0

    for promo in promotions:
        if is_expired(promo):
            print(f"[FILTER] 過期：{promo['title'][:50]}")
            excluded += 1
            continue

        if is_obviously_non_hotel(promo):
            print(f"[FILTER] 非酒店：{promo['title'][:50]}")
            excluded += 1
            continue

        filtered.append(promo)

    return filtered, excluded


def build_llm_content(filtered: list[dict]) -> str:
    """將預篩選後的優惠列表組合成 LLM 輸入文字。"""
    parts: list[str] = []
    for p in filtered:
        block = f"=== 優惠：{p['title']} ===\n"
        if p["date"]:
            block += f"發布日期：{p['date']}\n"
        block += p["content"]
        if p["url"]:
            block += f"\n優惠連結：{p['url']}"
        parts.append(block)

    return "\n\n".join(parts)[:MAX_LLM_CHARS]


# ─────────────────────────────────────────────────────────────────────────────
# 變更偵測
# ─────────────────────────────────────────────────────────────────────────────

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_last_hash() -> str:
    try:
        with open(HASH_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def save_hash(hash_value: str) -> None:
    with open(HASH_FILE, "w") as f:
        f.write(hash_value)


# ─────────────────────────────────────────────────────────────────────────────
# LLM 摘要
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(content: str) -> str:
    """使用模型備用鏈調用 OpenRouter。"""
    client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL_API,
        default_headers={
            "HTTP-Referer": "https://github.com/SkyEagle888/chinalink-hotel-monitor",
            "X-Title": "chinalink-hotel-monitor",
        },
    )

    last_error: Exception | None = None
    for model in MODELS:
        try:
            print(f"[INFO] 嘗試模型：{model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                extra_body={"application": "chinalink-hotel-monitor"},
                timeout=90,
            )
            result = response.choices[0].message.content.strip()
            print(f"[INFO] 成功使用模型：{model}")
            return result
        except Exception as e:
            print(f"[WARN] 模型 {model} 失敗：{e}")
            last_error = e
            time.sleep(2)

    raise RuntimeError(
        f"所有 LLM 模型均失敗。最後錯誤：{last_error}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Discord
# ─────────────────────────────────────────────────────────────────────────────

def post_to_discord(message: str) -> None:
    """透過 Incoming Webhook 向 Discord 發送訊息。"""
    if len(message) > 1950:
        message = message[:1947] + "..."

    payload = {
        "username": "🏨 酒店套票機器人",
        "content": message,
    }
    response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    response.raise_for_status()
    print(f"[INFO] Discord 通知已發送（{len(message)} 字元）")


def build_no_packages_message(excluded: int) -> str:
    """構建「無酒店套票」Discord 訊息（不經 LLM）。"""
    return (
        f"🔍 **環島中港通 酒店套票** | {TODAY_SHORT}\n\n"
        f"🔍 今日無酒店套票。已排除 {excluded} 個其他優惠。\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 查閱所有優惠 → "
        f"https://www.tilchinalink.com/promotions.php"
    )


def build_discord_message(summary: str) -> str:
    """根據 LLM 摘要組合完整 Discord 訊息。"""
    footer = (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━"
        "\n🔗 查閱所有優惠 → "
        "https://www.tilchinalink.com/promotions.php"
    )

    no_packages = (
        "今日無酒店套票" in summary
        or "0 個酒店套票" in summary
        or summary.strip().startswith("🔍")
    )

    if no_packages:
        header = (
            f"🔍 **環島中港通 酒店套票** "
            f"| {TODAY_SHORT}\n\n"
        )
    else:
        header = (
            f"🏨 **環島中港通 酒店套票快訊** "
            f"| {TODAY_SHORT}\n\n"
        )

    return header + summary + footer


# ─────────────────────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[INFO] 啟動酒店套票監察系統 — {TODAY_CN}")

    # 步驟 1：抓取
    try:
        raw_text, all_promotions = scrape_all_pages()
        print(
            f"[INFO] 已抓取 {len(raw_text):,} 字元，"
            f"共 {MAX_PAGES} 頁，"
            f"解析到 {len(all_promotions)} 個優惠"
        )
    except Exception as e:
        post_to_discord(
            f"⚠️ **優惠監察機器人錯誤** | {TODAY_SHORT}\n"
            f"抓取失敗：`{e}`\n"
            f"請手動檢查 → "
            f"https://www.tilchinalink.com/promotions.php"
        )
        return

    # 步驟 2：變更偵測
    current_hash = compute_hash(raw_text)
    if current_hash == load_last_hash():
        post_to_discord(
            f"ℹ️ 環島中港通 酒店套票 — "
            f"今日頁面無更新（{TODAY_SHORT}）"
        )
        print("[INFO] 無變更，提前退出。")
        return

    print("[INFO] 頁面內容已更新 — 進行預篩選")

    # 步驟 3：程序化預篩選
    if all_promotions:
        filtered, pre_excluded = prefilter(all_promotions)
    else:
        print("[WARN] 未能解析結構化優惠，回退至完整文字模式")
        filtered = []
        pre_excluded = 0

    print(
        f"[INFO] 預篩選：{len(filtered)} 個待檢查，"
        f"{pre_excluded} 個已排除"
    )

    if filtered:
        # 步驟 4a：有候選優惠 → 發送預篩選內容至 LLM
        llm_content = build_llm_content(filtered)
    elif not all_promotions:
        # 步驟 4b：HTML 結構變更 → 回退至完整文字
        llm_content = raw_text[:MAX_LLM_CHARS]
    else:
        # 步驟 4c：預篩選已排除所有優惠 → 跳過 LLM
        post_to_discord(build_no_packages_message(pre_excluded))
        save_hash(current_hash)
        print("[INFO] 預篩選已排除所有優惠，跳過 LLM。")
        return

    # 步驟 5：LLM 摘要
    try:
        summary = call_llm(llm_content)
    except Exception as e:
        post_to_discord(
            f"⚠️ **優惠監察機器人 LLM 錯誤** | {TODAY_SHORT}\n"
            f"摘要生成失敗：`{e}`\n抓取成功但未能生成摘要。"
        )
        return

    # 步驟 6：發送至 Discord
    try:
        message = build_discord_message(summary)
        post_to_discord(message)
    except Exception as e:
        print(f"[ERROR] Discord 發送失敗：{e}")
        return

    # 步驟 7：儲存新雜湊值
    save_hash(current_hash)
    print("[INFO] 雜湊值已更新。執行完成。")


if __name__ == "__main__":
    main()
