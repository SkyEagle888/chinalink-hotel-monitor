"""
環島中港通 — 每日酒店套票監察系統
抓取 promotions.php（繁體中文版），程序化預篩選以最小化 LLM 用量，
透過 OpenRouter LLM 生成繁體中文摘要，並發送至 Discord Webhook。
"""

import hashlib
import json
import os
import datetime
import time
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
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

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
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
    "表演套票", "表演門票",
]

HOTEL_KEYWORDS = ["住宿", "入住", "房間", "房"]
STAY_KEYWORDS = ["住宿", "入住", "房間", "房", "晚"]
MEAL_KEYWORDS = [
    "自助餐", "自助早餐", "自助晚餐",
    "早餐", "晚餐", "午宴", "Buffet", "buffet",
]

MAX_LLM_CHARS = 12000
PROMO_STALE_DAYS = int(os.environ.get("PROMO_STALE_DAYS", "180"))
SELF_CONSISTENCY_RUNS = int(os.environ.get("SELF_CONSISTENCY_RUNS", "2"))
URL_RETRY_LIMIT = int(os.environ.get("URL_RETRY_LIMIT", "1"))

DYNAMIC_CLASS_PATTERN = re.compile(
    r"^(ad|ads|ad-banner|ad-container|ad-wrapper|"
    r"counter|view-count|view-counter|page-views|"
    r"timestamp|last-updated|updated-at)$",
    re.I,
)

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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
輸出格式：JSON 物件（不可含說明、Markdown 區塊或前後註解）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

JSON 結構：
{{
  "packages": [
    {{
      "title": "套票名稱",
      "validity": "有效日期範圍，無結束日期則填「持續有效」",
      "price": "每位／每套票價，否則填「請查閱官網」",
      "dining": "自助餐或早餐詳情",
      "nights": 1,
      "room_type": "房型描述，無則填「標準房」",
      "booking": "訂票渠道：微信小程式 / 支付寶 / 售票中心",
      "note": "一句限制或亮點",
      "url": "此優惠的個別 URL"
    }}
  ],
  "excluded_count": 已預篩選後剩餘的優惠中，LLM 排除的數量（整數）
}}

規則：
1. packages 為陣列，僅含合資格、仍然有效的酒店套票。
2. 已過期或不合資格 → 不加入 packages。
3. excluded_count = 你（LLM）在本次輸入中「掃描但判定為非酒店」的數量。
4. nights 必須為整數，無法判斷時填 1。
5. url 必須與輸入中的優惠連結一致；不得編造。
6. 所有字串使用繁體中文。
7. 不輸出交通時間表、班次或路線詳情。
8. 每個套票的 note 不超過一句。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
示範範例（Few-shot：2 合資格 + 2 排除）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

範例 1 — 合資格酒店套票（明確住宿+交通+餐飲）：
輸入：
=== 優惠：珠海希爾頓花園酒店 2人套票 ===
發布日期：2026-06-01
入住希爾頓花園酒店 1晚 標準大床房，包自助早餐 2位
+ 來回直通巴士接送 香港上車點至酒店
每位 HK$988 起
優惠連結：https://www.tilchinalink.com/promotions.php?id=201
輸出：
{{"packages":[{{"title":"珠海希爾頓花園酒店 2人套票","validity":"持續有效","price":"每位 HK$988 起","dining":"自助早餐 2位","nights":1,"room_type":"標準大床房","booking":"微信小程式","note":"需 2 位成行","url":"https://www.tilchinalink.com/promotions.php?id=201"}}],"excluded_count":0}}

範例 2 — 合資格酒店套票（含明確結束日期）：
輸入：
=== 優惠：中山溫泉賓館家庭套票 ===
發布日期：2026-05-15
中山溫泉賓館 高級溫泉房 2晚 + 2位自助晚餐 + 來回車票
有效期：2026年5月20日 至 2026年8月31日
每套 HK$1,580
優惠連結：https://www.tilchinalink.com/promotions.php?id=205
輸出：
{{"packages":[{{"title":"中山溫泉賓館家庭套票","validity":"2026年5月20日 至 2026年8月31日","price":"每套 HK$1,580","dining":"自助晚餐 2位","nights":2,"room_type":"高級溫泉房","booking":"售票中心","note":"暑假旺季","url":"https://www.tilchinalink.com/promotions.php?id=205"}}],"excluded_count":0}}

範例 3 — 演唱會套票（嚴格排除）：
輸入：
=== 優惠：郭富城演唱會澳門站 酒店車票套票 ===
發布日期：2026-05-20
澳門威尼斯人 1晚 標準房 + 來回直通巴士 + 郭富城演唱會 A 區門票 2位
優惠連結：https://www.tilchinalink.com/promotions.php?id=210
輸出：
{{"packages":[],"excluded_count":1}}

範例 4 — 純車費優惠（酒店名稱僅為站點）：
輸入：
=== 優惠：花山新增站點限定優惠 — 買去程送回程 ===
發布日期：2026-06-03
花山希爾頓歡朋酒店為新登車站點，買去程送回程
每位 HK$120 起
優惠連結：https://www.tilchinalink.com/promotions.php?id=212
輸出：
{{"packages":[],"excluded_count":1}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
現在請處理以下用戶提供的優惠，僅回傳 JSON：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
    """從優惠內容提取所有結束日期。

    支援格式：
      - YYYY年M月D日 至 YYYY年M月D日
      - YYYY年M月D日 至 M月D日（無年，ref_year 推導）
      - 至 YYYY年M月D日
      - YYYY/MM/DD 或 DD/MM/YYYY（slash 格式）
      - 至 YYYY-MM-DD（dash 格式，內容內）
    """
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

    for m in re.finditer(
        r"(\d{4})/(\d{1,2})/(\d{1,2})"
        r"\s*[至到\–\-~]\s*"
        r"(\d{4})/(\d{1,2})/(\d{1,2})",
        text,
    ):
        d = _safe_date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        if d:
            dates.append(d)

    for m in re.finditer(
        r"(\d{1,2})/(\d{1,2})/(\d{4})"
        r"\s*[至到\–\-~]\s*"
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
        text,
    ):
        d = _safe_date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
        if d:
            dates.append(d)

    for m in re.finditer(
        r"[至到]\s*(\d{4})/(\d{1,2})/(\d{1,2})", text
    ):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            dates.append(d)

    for m in re.finditer(
        r"[至到]\s*(\d{1,2})/(\d{1,2})/(\d{4})", text
    ):
        d = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            dates.append(d)

    for m in re.finditer(
        r"[至到]\s*(\d{4})-(\d{1,2})-(\d{1,2})", text
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

    for el in soup.find_all(class_=DYNAMIC_CLASS_PATTERN):
        el.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return text, promotions


def _is_page_stale(promos: list[dict]) -> bool:
    """整頁所有有日期的優惠均早於 PROMO_STALE_DAYS 天則視為過期。"""
    dated: list[datetime.date] = []
    for p in promos:
        ds = p.get("date", "")
        if not ds:
            continue
        try:
            dated.append(datetime.datetime.strptime(ds, "%Y-%m-%d").date())
        except ValueError:
            continue
    if not dated:
        return False
    return (TODAY - max(dated)).days > PROMO_STALE_DAYS


def scrape_all_pages() -> tuple[str, list[dict], int]:
    """並行抓取第 1–MAX_PAGES 頁 (T9.4.1)。

    使用 ThreadPoolExecutor 同時發出 3 個 GET 請求，最後依頁碼順序組裝並套用
    早停邏輯 (T9.4.2 / FR-1.3)：若當前頁所有優惠均早於 PROMO_STALE_DAYS 天，
    後續頁面雖已抓取亦不納入結果。

    回傳 (text, promotions, pages_scanned)。
    """
    results: dict[int, tuple[str, list[dict]]] = {}

    with ThreadPoolExecutor(max_workers=MAX_PAGES) as executor:
        futures = {
            executor.submit(fetch_page, i): i
            for i in range(1, MAX_PAGES + 1)
        }
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                results[page_num] = future.result()
            except requests.RequestException as e:
                if page_num == 1:
                    raise
                print(f"[WARN] 第 {page_num} 頁抓取失敗：{e}")

    all_text: list[str] = []
    all_promotions: list[dict] = []
    pages_scanned = 0

    for i in sorted(results.keys()):
        text, promos = results[i]
        all_text.append(f"=== 優惠頁面 {i} ===\n{text}")
        all_promotions.extend(promos)
        pages_scanned += 1
        if _is_page_stale(promos):
            print(
                f"[INFO] 第 {i} 頁全部優惠早於 "
                f"{PROMO_STALE_DAYS} 天，停止翻頁 (FR-1.3)"
            )
            break

    combined_text = "\n\n".join(all_text)
    return combined_text, all_promotions, pages_scanned


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


def has_hotel_keyword(promo: dict) -> bool:
    """正向白名單：「住宿」「入住」「房間」至少一項出現。"""
    combined = promo.get("title", "") + " " + promo.get("content", "")
    return any(kw in combined for kw in HOTEL_KEYWORDS)


def has_stay_and_meal(promo: dict) -> bool:
    """T9.4.3 雙關鍵字命中：住宿 + 餐飲皆出現。"""
    combined = promo.get("title", "") + " " + promo.get("content", "")
    has_stay = any(kw in combined for kw in STAY_KEYWORDS)
    has_meal = any(kw in combined for kw in MEAL_KEYWORDS)
    return has_stay and has_meal


HEURISTIC_2ND_ROUND_THRESHOLD = 3


def prefilter(
    promotions: list[dict],
) -> tuple[list[dict], int]:
    """程序化預篩選。回傳 (filtered_list, excluded_count)。

    流程：
      1. is_expired — 排除過期
      2. is_obviously_non_hotel — 排除明確非酒店
      3. has_hotel_keyword (T9.3.2) — 排除無住宿關鍵字
      4. 候選 >= 3 → 啟發式第二輪 (T9.4.3) 雙關鍵字命中
    """
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

        if not has_hotel_keyword(promo):
            print(f"[FILTER] 無住宿關鍵字：{promo['title'][:50]}")
            excluded += 1
            continue

        filtered.append(promo)

    if len(filtered) >= HEURISTIC_2ND_ROUND_THRESHOLD:
        round1_count = len(filtered)
        round2 = [p for p in filtered if has_stay_and_meal(p)]
        if len(round2) < round1_count:
            print(
                f"[FILTER] 啟發式第二輪：{round1_count} → {len(round2)} "
                f"（雙關鍵字：住宿+餐飲）"
            )
            excluded += round1_count - len(round2)
            filtered = round2

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

def call_llm(content: str) -> dict:
    """LLM 調用：self-consistency (T9.5.3) + URL 驗證重試 (T9.3.3)。

    回傳結構：{"packages": [{"title", "validity", "price", "dining",
    "nights", "room_type", "booking", "note", "url"}, ...],
    "excluded_count": int}
    """
    if SELF_CONSISTENCY_RUNS <= 1:
        return _call_llm_with_url_retry(content)

    runs: list[dict] = []
    for run_n in range(SELF_CONSISTENCY_RUNS):
        try:
            runs.append(_call_llm_with_url_retry(content))
        except RuntimeError:
            if not runs:
                raise
            print(
                f"[WARN] Self-consistency 第 {run_n + 1} 輪失敗，沿用前 {len(runs)} 輪"
            )
            break

    if len(runs) == 1:
        return runs[0]
    return _intersect_runs(runs)


def _call_llm_with_url_retry(content: str) -> dict:
    """單輪 LLM 調用 + URL 驗證重試 (T9.3.3)。"""
    last_data: dict | None = None
    for attempt in range(URL_RETRY_LIMIT + 1):
        data = _call_single_run(content)
        last_data = data
        invalid = _validate_urls(data)
        if not invalid:
            return data
        if attempt < URL_RETRY_LIMIT:
            print(
                f"[WARN] {len(invalid)} 個套件 URL 無效，"
                f"重試 ({attempt + 1}/{URL_RETRY_LIMIT})"
            )
            continue
        print(
            f"[WARN] 重試後仍有 {len(invalid)} 個 URL 無效，移除："
            f"{invalid[:3]}"
        )
        return _drop_invalid_urls(data)
    return last_data or {"packages": [], "excluded_count": 0}


def _call_single_run(content: str) -> dict:
    """單次 LLM 調用（3 模型備用鏈）。"""
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
                response_format={"type": "json_object"},
                extra_body={"application": "chinalink-hotel-monitor"},
                timeout=90,
            )
            raw = response.choices[0].message.content.strip()
            print(f"[INFO] 成功使用模型：{model}")
            return _parse_llm_json(raw)
        except Exception as e:
            print(f"[WARN] 模型 {model} 失敗：{e}")
            last_error = e
            time.sleep(2)

    raise RuntimeError(
        f"所有 LLM 模型均失敗。最後錯誤：{last_error}"
    )


def _validate_urls(llm_data: dict) -> list[str]:
    """回傳 URL 缺失或不含 `id=` 的套件標題清單。"""
    invalid: list[str] = []
    for pkg in llm_data.get("packages", []):
        url = pkg.get("url", "")
        if not url or "id=" not in url:
            invalid.append(pkg.get("title") or "<未命名>")
    return invalid


def _drop_invalid_urls(llm_data: dict) -> dict:
    """移除 URL 無效的套件，excluded_count 對應增加。"""
    packages = llm_data.get("packages", [])
    valid = [
        p for p in packages
        if p.get("url") and "id=" in p.get("url", "")
    ]
    dropped = len(packages) - len(valid)
    if dropped:
        llm_data["excluded_count"] = llm_data.get("excluded_count", 0) + dropped
        llm_data["packages"] = valid
    return llm_data


def _intersect_runs(runs: list[dict]) -> dict:
    """Self-consistency (T9.5.3)：多輪結果取 URL 交集。

    - 交集為空時 fallback 至第一輪（避免 false negative）
    - excluded_count 取各輪最大值
    """
    if not runs:
        return {"packages": [], "excluded_count": 0}
    if len(runs) == 1:
        return runs[0]

    base = runs[0]
    base_urls = {p.get("url"): p for p in base["packages"]}
    common: set[str] = set(base_urls.keys())

    for other in runs[1:]:
        other_urls = {p.get("url") for p in other["packages"]}
        common &= other_urls

    if common:
        base["packages"] = [p for url, p in base_urls.items() if url in common]
    base["excluded_count"] = max(r.get("excluded_count", 0) for r in runs)
    return base


def _parse_llm_json(raw: str) -> dict:
    """解析 LLM 回傳的 JSON 內容，容錯處理缺欄位或型別錯誤。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"LLM 回應非合法 JSON：{e}; raw={raw[:200]}"
        ) from e

    if not isinstance(data, dict):
        raise RuntimeError(
            f"LLM 回應不是 JSON 物件：{type(data).__name__}"
        )

    packages = data.get("packages", [])
    if not isinstance(packages, list):
        packages = []

    excluded = data.get("excluded_count", 0)
    if not isinstance(excluded, int) or isinstance(excluded, bool):
        excluded = 0

    normalized: list[dict] = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        try:
            nights = int(pkg.get("nights", 1))
        except (TypeError, ValueError):
            nights = 1
        normalized.append({
            "title": str(pkg.get("title", "")).strip(),
            "validity": str(pkg.get("validity", "持續有效")).strip() or "持續有效",
            "price": str(pkg.get("price", "請查閱官網")).strip() or "請查閱官網",
            "dining": str(pkg.get("dining", "")).strip(),
            "nights": nights,
            "room_type": str(pkg.get("room_type", "標準房")).strip() or "標準房",
            "booking": str(pkg.get("booking", "微信小程式")).strip() or "微信小程式",
            "note": str(pkg.get("note", "")).strip(),
            "url": str(pkg.get("url", "")).strip(),
        })

    return {"packages": normalized, "excluded_count": excluded}


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


def _render_package_block(pkg: dict) -> str:
    """將單一套票 JSON 物件渲染為 SCOPE.md §7 格式的 Markdown 區塊。"""
    title = pkg.get("title") or "未命名套票"
    validity = pkg.get("validity") or "持續有效"
    price = pkg.get("price") or "請查閱官網"
    dining = pkg.get("dining") or "請查閱官網"
    room_type = pkg.get("room_type") or "標準房"
    booking = pkg.get("booking") or "微信小程式"
    note = pkg.get("note") or "—"
    nights = pkg.get("nights", 1)
    url = pkg.get("url") or ""

    block = (
        f"🏨 **{title}**\n"
        f"📅 有效期：{validity}\n"
        f"💰 價格：{price}\n"
        f"🍽️ 餐飲：{dining}\n"
        f"🛏️ 住宿：{nights} 晚，{room_type}\n"
        f"📲 訂票：{booking}\n"
        f"📝 備注：{note}"
    )
    if url:
        block += f"\n🔗 優惠詳情：{url}"
    return block


def _render_packages_markdown(llm_data: dict) -> str:
    """將 LLM JSON 結果渲染為 SCOPE.md §7 格式的 Markdown 摘要。"""
    packages = llm_data.get("packages", [])
    excluded = llm_data.get("excluded_count", 0)

    if not packages:
        return f"🔍 今日無酒店套票。已排除 {excluded} 個其他優惠。"

    blocks = [_render_package_block(p) for p in packages]
    summary = "\n\n".join(blocks)
    summary += (
        f"\n\n✅ 找到 {len(packages)} 個酒店套票 | "
        f"🚫 已排除 {excluded} 個非酒店優惠"
    )
    return summary


def build_stats_footer(
    pages_scanned: int,
    total_promos: int,
    pre_filtered: int,
    llm_candidates: int,
    hotel_count: int,
) -> str:
    """構建統計資訊頁尾。"""
    return (
        f"📊 掃描：{pages_scanned} 頁 | "
        f"優惠：{total_promos} | "
        f"預篩排除：{pre_filtered} | "
        f"LLM 分析：{llm_candidates} | "
        f"酒店套票：{hotel_count}"
    )


def build_no_packages_message(
    excluded: int,
    stats: dict,
) -> str:
    """構建「無酒店套票」Discord 訊息（不經 LLM）。"""
    stats_footer = build_stats_footer(
        stats["pages_scanned"],
        stats["total_promos"],
        excluded,
        0,
        0,
    )
    return (
        f"🔍 **環島中港通 酒店套票** | {TODAY_SHORT}\n\n"
        f"🔍 今日無酒店套票。已排除 {excluded} 個其他優惠。\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{stats_footer}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 查閱所有優惠 → "
        f"https://www.tilchinalink.com/promotions.php"
    )


def build_discord_message(llm_data: dict, stats: dict) -> str:
    """根據 LLM 結構化結果組合完整 Discord 訊息（SCOPE.md §7 格式）。"""
    hotel_count = len(llm_data.get("packages", []))
    summary = _render_packages_markdown(llm_data)

    stats_footer = build_stats_footer(
        stats["pages_scanned"],
        stats["total_promos"],
        stats["pre_filtered"],
        stats["llm_candidates"],
        hotel_count,
    )

    footer = (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━"
        f"\n{stats_footer}"
        "\n━━━━━━━━━━━━━━━━━━━━━━"
        "\n🔗 查閱所有優惠 → "
        "https://www.tilchinalink.com/promotions.php"
    )

    if hotel_count == 0:
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
        raw_text, all_promotions, pages_scanned = scrape_all_pages()
        print(
            f"[INFO] 已抓取 {len(raw_text):,} 字元，"
            f"共 {pages_scanned} 頁，"
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

    stats: dict = {
        "pages_scanned": pages_scanned,
        "total_promos": len(all_promotions),
        "pre_filtered": 0,
        "llm_candidates": 0,
    }

    # 步驟 2：變更偵測
    current_hash = compute_hash(raw_text)
    if current_hash == load_last_hash():
        stats_no_change = build_stats_footer(pages_scanned, len(all_promotions), 0, 0, 0)
        post_to_discord(
            f"ℹ️ **環島中港通 酒店套票** — "
            f"今日頁面無更新（{TODAY_SHORT}）\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{stats_no_change}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 查閱所有優惠 → "
            f"https://www.tilchinalink.com/promotions.php"
        )
        print("[INFO] 無變更，提前退出。")
        return

    print("[INFO] 頁面內容已更新 — 進行預篩選")

    # 步驟 3：程序化預篩選
    if all_promotions:
        filtered, pre_excluded = prefilter(all_promotions)
        stats["pre_filtered"] = pre_excluded
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
        stats["llm_candidates"] = len(filtered)
    elif not all_promotions:
        # 步驟 4b：HTML 結構變更 → 回退至完整文字
        llm_content = raw_text[:MAX_LLM_CHARS]
        stats["llm_candidates"] = 1
    else:
        # 步驟 4c：預篩選已排除所有優惠 → 跳過 LLM
        post_to_discord(build_no_packages_message(pre_excluded, stats))
        save_hash(current_hash)
        print("[INFO] 預篩選已排除所有優惠，跳過 LLM。")
        return

    # 步驟 5：LLM 摘要
    try:
        llm_data = call_llm(llm_content)
    except Exception as e:
        post_to_discord(
            f"⚠️ **優惠監察機器人 LLM 錯誤** | {TODAY_SHORT}\n"
            f"摘要生成失敗：`{e}`\n抓取成功但未能生成摘要。"
        )
        return

    # 步驟 6：發送至 Discord
    try:
        message = build_discord_message(llm_data, stats)
        post_to_discord(message)
    except Exception as e:
        print(f"[ERROR] Discord 發送失敗：{e}")
        return

    # 步驟 7：儲存新雜湊值
    save_hash(current_hash)
    print("[INFO] 雜湊值已更新。執行完成。")


if __name__ == "__main__":
    main()
