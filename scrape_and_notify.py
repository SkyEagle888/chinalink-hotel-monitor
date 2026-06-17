"""
環島中港通 — 每日酒店套票監察系統（v1.3）

抓取 hotel_packages.php?lang=tc（網站已預先篩選為「酒店套票」之頁面），
依用戶指定地區（深圳/廣州/中山/珠海）過濾卡片，再以程序化規則排除
滑雪套票，並透過並行的 detail-page 抓取豐富每個套票的資訊，
最終透過 Discord Webhook 發送繁體中文摘要通知。

v1.3 主要變更（與 v1.2 對比）：
  - 目標網址：promotions.php → hotel_packages.php?lang=tc
  - 不再調用 LLM（依網站自身策展信任為「酒店套票」）
  - 新增地區過濾 INCLUDE_REGIONS
  - 新增 fetch_detail_pages()：並行抓取每張卡片的詳細頁，提取發布日期
  - HTML 解析改為卡片網格結構（<a class="package-wrapper">）
  - Discord 訊息按地區分組，呈現每個套票
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup, Tag

# ─────────────────────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = "https://www.tilchinalink.com/hotel_packages.php?lang=tc"
MAX_PAGES = 1
HASH_FILE = "last_hash.txt"
PROMOS_FILE = "last_promos.json"
TODAY = datetime.date.today()
TODAY_CN = TODAY.strftime("%Y年%m月%d日")
TODAY_SHORT = TODAY.strftime("%d/%m/%Y")

RUN_ID = os.environ.get("RUN_ID", uuid.uuid4().hex[:12])

# Secrets — DISCORD_WEBHOOK_URL 仍需保留，OPENROUTER_API_KEY 在 v1.3 已不再使用
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# v1.3 — 用戶指定監察的地區（依 SCOPE §11）
INCLUDE_REGIONS = ["深圳", "廣州", "中山", "珠海"]
REGION_RANK = {r: i for i, r in enumerate(INCLUDE_REGIONS)}

# v1.3 — 唯一保留的關鍵詞排除（依 SCOPE §3.2 + 用戶決定）
EXCLUDE_KEYWORDS = ["滑雪", "雪場", "雪場套票"]

# v1.3 — 為正向白名單保留（hotel_packages.php 內容已策展，仍做最後防線）
HOTEL_KEYWORDS = ["住宿", "入住", "房間", "房"]
STAY_KEYWORDS = ["住宿", "入住", "房間", "房", "晚"]
MEAL_KEYWORDS = [
    "自助餐", "自助早餐", "自助晚餐",
    "早餐", "晚餐", "午宴", "Buffet", "buffet",
]

PROMO_STALE_DAYS = int(os.environ.get("PROMO_STALE_DAYS", "180"))
DISCORD_RETRY_MAX = int(os.environ.get("DISCORD_RETRY_MAX", "3"))
DISCORD_RETRY_BACKOFF = float(os.environ.get("DISCORD_RETRY_BACKOFF", "2"))
DETAIL_FETCH_TIMEOUT = int(os.environ.get("DETAIL_FETCH_TIMEOUT", "15"))
DETAIL_FETCH_WORKERS = int(os.environ.get("DETAIL_FETCH_WORKERS", "4"))
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

DYNAMIC_CLASS_PATTERN = re.compile(
    r"^(ad|ads|ad-banner|ad-container|ad-wrapper|"
    r"counter|view-count|view-counter|page-views|"
    r"timestamp|last-updated|updated-at)$",
    re.I,
)

DATE_RE = re.compile(r"(?:發布|發佈)日期[:：]\s*(\d{4}-\d{2}-\d{2})")
NIGHTS_RE = re.compile(r"(\d+)\s*晚")
DINING_KEYWORDS_RE = re.compile(
    r"(自助[餐早晚]|早餐|晚餐|Buffet|buffet)"
)
TRANSPORT_KEYWORDS_RE = re.compile(
    r"(直通巴士|跨境巴士|巴士|客車|豪華轎車|車票|直通車)"
)
ROOM_TYPE_RE = re.compile(
    r"(標準[大雙單]床房|豪華[大雙單]床房|行政套房|家庭房|高級房|套房|標準房|大床房|雙床房)"
)


# ─────────────────────────────────────────────────────────────────────────────
# 結構化日誌 (T9.6.2)
# ─────────────────────────────────────────────────────────────────────────────

_STRUCT_LOGGER = logging.getLogger("hotel_monitor")
_STRUCT_LOGGER.setLevel(logging.INFO)
if not _STRUCT_LOGGER.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _STRUCT_LOGGER.addHandler(_handler)
    _STRUCT_LOGGER.propagate = False


def _log_event(event: str, **fields) -> None:
    """發送結構化 JSON 日誌事件 (T9.6.2)。

    每行均含 `ts` / `level` / `run_id` / `event`，額外欄位可由 kwargs 注入。
    """
    payload = {
        "ts": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "level": "INFO",
        "run_id": RUN_ID,
        "event": event,
        **fields,
    }
    _STRUCT_LOGGER.info(json.dumps(payload, ensure_ascii=False))


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
# 抓取 hotel_packages.php 卡片
# ─────────────────────────────────────────────────────────────────────────────

def parse_promotion(anchor: Tag) -> dict | None:
    """從卡片錨點 `<a class="package-wrapper">` 提取結構化資料。

    回傳 dict：{title, region, price, url} 或 None（如缺標題）。
    """
    href = anchor.get("href", "")
    if not href:
        return None

    title_el = anchor.find(["h3", "h4"])
    title = title_el.get_text(strip=True) if title_el else ""

    region_el = anchor.find(class_="package-location")
    region_text = region_el.get_text(strip=True) if region_el else ""
    region = region_text.replace("📍", "").strip()

    price_el = anchor.find(class_="package-price")
    price = price_el.get_text(strip=True) if price_el else ""
    unit_el = anchor.find(class_="package-unit")
    unit = unit_el.get_text(strip=True) if unit_el else ""

    if not title:
        return None

    return {
        "title": title,
        "region": region,
        "price": (price + unit).strip(),
        "url": href,
    }


def fetch_page(page_num: int) -> tuple[str, list[dict]]:
    """抓取單頁（v1.3：hotel_packages.php?lang=tc，單頁，無分頁）。

    回傳 (raw_text, promotions_list)。
    """
    url = BASE_URL if page_num == 1 else f"{BASE_URL}&page={page_num}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    promotions: list[dict] = []
    for anchor in soup.find_all("a", class_="package-wrapper"):
        promo = parse_promotion(anchor)
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
    """v1.3：抓取單一 hotel_packages.php 頁面（無分頁）。

    保留 MAX_PAGES 常數以便日後網站加入分頁時無需修改介面。
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
        all_text.append(f"=== 酒店套票頁面 {i} ===\n{text}")
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
# Detail-page 抓取（並行）
# ─────────────────────────────────────────────────────────────────────────────

def fetch_detail_page(url: str) -> dict:
    """抓取單一 hotel 套票 detail page，提取發布日期與摘要資訊。

    回傳 dict：
      - date: 發布日期（YYYY-MM-DD）或空字串
      - summary: 去除 base64 圖片後的純文字摘要
      - nights, dining, transport, room_type: 從文字中抽取（可能為 None）
    """
    result: dict = {
        "url": url,
        "date": "",
        "summary": "",
        "nights": None,
        "dining": None,
        "transport": None,
        "room_type": None,
    }
    try:
        resp = requests.get(url, headers=HEADERS, timeout=DETAIL_FETCH_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[WARN] 詳情頁抓取失敗 {url}: {e}")
        return result

    soup = BeautifulSoup(resp.text, "html.parser")

    faintivory = soup.find("div", class_="faintivory-background")
    if not faintivory:
        return result

    date_match = DATE_RE.search(faintivory.get_text(" ", strip=True))
    if date_match:
        result["date"] = date_match.group(1)

    for img in faintivory.find_all("img"):
        img.decompose()

    text = faintivory.get_text(" ", strip=True)
    if len(text) > 500:
        text = text[:497] + "..."
    result["summary"] = text

    nights_match = NIGHTS_RE.search(text)
    if nights_match:
        try:
            result["nights"] = int(nights_match.group(1))
        except ValueError:
            pass

    if DINING_KEYWORDS_RE.search(text):
        result["dining"] = "自助餐／早餐"

    if TRANSPORT_KEYWORDS_RE.search(text):
        result["transport"] = "直通巴士"

    room_match = ROOM_TYPE_RE.search(text)
    if room_match:
        result["room_type"] = room_match.group(1)

    return result


def fetch_detail_pages(promos: list[dict]) -> list[dict]:
    """並行抓取所有 unique 詳情頁，enrich 每張卡片。

    同一 URL 多張卡片共享同一份 detail 結果。回傳與輸入等長的 enriched list。
    """
    unique_urls = sorted({p["url"] for p in promos if p.get("url")})
    if not unique_urls:
        return promos

    print(f"[INFO] 並行抓取 {len(unique_urls)} 個唯一詳情頁")

    detail_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=DETAIL_FETCH_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_detail_page, url): url for url in unique_urls
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                detail_map[url] = future.result()
            except Exception as e:
                print(f"[WARN] 詳情頁並行失敗 {url}: {e}")
                detail_map[url] = {"url": url, "date": "", "summary": ""}

    enriched: list[dict] = []
    for p in promos:
        detail = detail_map.get(p["url"], {})
        merged = dict(p)
        merged["date"] = detail.get("date", "") or p.get("date", "")
        merged["summary"] = detail.get("summary", "")
        for key in ("nights", "dining", "transport", "room_type"):
            val = detail.get(key)
            if val is not None:
                merged[key] = val
        enriched.append(merged)

    return enriched


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
        promo.get("content", "") or promo.get("summary", ""),
        publish_date.year,
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
    combined = (
        promo.get("title", "")
        + " "
        + promo.get("content", "")
        + " "
        + promo.get("summary", "")
    )
    for kw in EXCLUDE_KEYWORDS:
        if kw in combined:
            return True
    return False


def has_hotel_keyword(promo: dict) -> bool:
    """v1.3 正向白名單。

    規則：
      1. 「住宿」/「入住」/「房間」/「房」任一出現 → 通過
      2. 標題含「酒店套票」或「酒店住宿」複合詞 → 通過（hotel_packages.php 卡片）
    """
    title = promo.get("title", "")
    combined = (
        title + " " +
        promo.get("content", "") + " " +
        promo.get("summary", "")
    )
    if any(kw in combined for kw in HOTEL_KEYWORDS):
        return True
    if "酒店套票" in title or "酒店住宿" in title:
        return True
    return False

def region_allowed(promo: dict) -> bool:
    """v1.3：地區白名單（依用戶指定 INCLUDE_REGIONS）。

    若卡片無 region 資訊（例如來自舊黃金集），預設放行以保持向後相容。
    """
    region = promo.get("region", "")
    if not region:
        return True
    return region in INCLUDE_REGIONS


def prefilter(
    promotions: list[dict],
) -> tuple[list[dict], int]:
    """v1.3 程序化預篩選。

    流程：
      1. region_allowed — 排除不在 INCLUDE_REGIONS 之地區
      2. is_expired — 排除過期
      3. is_obviously_non_hotel — 排除關鍵詞命中（滑雪/雪場）

    注意：v1.3 不再使用 has_hotel_keyword 白名單 — hotel_packages.php 頁面
    已由網站策展為「酒店套票」專屬頁，依用戶選擇信任網站策展（Path A）。
    """
    filtered: list[dict] = []
    excluded = 0

    for promo in promotions:
        if not region_allowed(promo):
            print(f"[FILTER] 地區不符：{promo['title'][:40]}")
            excluded += 1
            continue

        if is_expired(promo):
            print(f"[FILTER] 過期：{promo['title'][:40]}")
            excluded += 1
            continue

        if is_obviously_non_hotel(promo):
            print(f"[FILTER] 排除關鍵詞：{promo['title'][:40]}")
            excluded += 1
            continue

        filtered.append(promo)

    return filtered, excluded
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


def load_last_promos() -> list[dict]:
    """載入上一輪抓取的優惠清單 (T9.6.3)。"""
    try:
        with open(PROMOS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_last_promos(promos: list[dict]) -> None:
    """將本次抓取的優惠清單持久化，供下次比對。"""
    with open(PROMOS_FILE, "w", encoding="utf-8") as f:
        json.dump(promos, f, ensure_ascii=False)


def compute_promo_diff(
    old: list[dict], new: list[dict]
) -> dict[str, list[str]]:
    """比對兩輪抓取結果，回傳 {added, removed} URL 清單 (T9.6.3)。

    比對鍵為 `url`（個別優惠的 `?id=XXX` 連結）。
    """
    old_urls = {p.get("url", "") for p in old if p.get("url")}
    new_urls = {p.get("url", "") for p in new if p.get("url")}

    added = sorted(new_urls - old_urls)
    removed = sorted(old_urls - new_urls)
    return {"added": added, "removed": removed}


def compute_per_page_hashes(
    pages: dict[int, str],
) -> dict[int, str]:
    """逐頁雜湊 (T9.6.3)，用於日誌觀測變更範圍。"""
    return {
        page: hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        for page, text in pages.items()
    }


# ─────────────────────────────────────────────────────────────────────────────
# Discord 訊息構建
# ─────────────────────────────────────────────────────────────────────────────

def _render_package_block(pkg: dict) -> str:
    """將單一卡片渲染為 SCOPE §7 變體的 Markdown 區塊。"""
    title = pkg.get("title") or "未命名套票"
    price = pkg.get("price", "") or "請查閱官網"
    nights = pkg.get("nights")
    room_type = pkg.get("room_type") or "請查閱官網"
    dining = pkg.get("dining") or "請查閱官網"
    transport = pkg.get("transport") or "請查閱官網"
    date = pkg.get("date") or "—"
    url = pkg.get("url") or ""

    if nights:
        stay = f"{nights} 晚，{room_type}"
    else:
        stay = f"晚數請查官網，{room_type}"

    if price.startswith("HK$"):
        price_display = price
    elif price.startswith("$"):
        price_display = "HK" + price
    elif price == "請查閱官網":
        price_display = price
    else:
        price_display = f"HK${price}"

    block = (
        f"🏨 **{title}**\n"
        f"💰 價格：{price_display}"
    )

    block += (
        f"\n🛏️ 住宿：{stay}"
        f"\n🍽️ 餐飲：{dining}"
        f"\n🚍 交通：{transport}"
        f"\n📅 發布：{date}"
    )
    if url:
        block += f"\n🔗 優惠詳情：{url}"
    return block


def _build_region_section(region: str, packages: list[dict]) -> str:
    """單一地區的 Discord 區塊（含標題與所有套票）。"""
    header = f"━━ {region}（{len(packages)} 個套票） ━━"
    blocks = [_render_package_block(p) for p in packages]
    return header + "\n\n" + "\n\n".join(blocks)


def sort_by_region(packages: list[dict]) -> list[dict]:
    """依 INCLUDE_REGIONS 順序排列卡片（同地區內保持輸入順序）。"""
    def key(p: dict) -> tuple[int, int]:
        region = p.get("region", "")
        rank = REGION_RANK.get(region, len(INCLUDE_REGIONS))
        return (rank, 0)
    return sorted(packages, key=key)


def group_by_region(packages: list[dict]) -> list[tuple[str, list[dict]]]:
    """將卡片依地區分組，僅回傳有卡片的地區（依 INCLUDE_REGIONS 順序）。"""
    buckets: dict[str, list[dict]] = {r: [] for r in INCLUDE_REGIONS}
    for p in packages:
        region = p.get("region", "")
        if region in buckets:
            buckets[region].append(p)

    return [(r, buckets[r]) for r in INCLUDE_REGIONS if buckets[r]]


def build_stats_footer(
    pages_scanned: int,
    total_promos: int,
    region_excluded: int,
    other_excluded: int,
    hotel_count: int,
) -> str:
    """構建統計資訊頁尾。"""
    return (
        f"📊 掃描：{pages_scanned} 頁 | "
        f"卡片：{total_promos} | "
        f"地區排除：{region_excluded} | "
        f"其他排除：{other_excluded} | "
        f"最終保留：{hotel_count}"
    )


def build_no_packages_message(
    excluded: int,
    stats: dict,
    active_regions: list[str] | None = None,
) -> str:
    """構建「無酒店套票」Discord 訊息（不經 LLM）。"""
    regions_text = (
        " / ".join(active_regions) if active_regions else "指定地區"
    )
    stats_footer = build_stats_footer(
        stats["pages_scanned"],
        stats["total_promos"],
        stats.get("region_excluded", 0),
        excluded,
        0,
    )
    return (
        f"🔍 **環島中港通 酒店套票** | {TODAY_SHORT}\n\n"
        f"🔍 今日「{regions_text}」無酒店套票。"
        f"已排除 {excluded} 個其他地區或非酒店優惠。\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{stats_footer}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 查閱所有套票 → "
        f"{BASE_URL}"
    )


def build_discord_message(
    packages: list[dict],
    stats: dict,
    region_excluded: int,
    other_excluded: int,
) -> str:
    """構建 v1.3 Discord 訊息（按地區分組）。"""
    hotel_count = len(packages)

    if hotel_count == 0:
        return build_no_packages_message(
            excluded=region_excluded + other_excluded,
            stats=stats,
            active_regions=None,
        )

    sorted_pkgs = sort_by_region(packages)
    grouped = group_by_region(sorted_pkgs)
    active_regions = [r for r, _ in grouped]

    header = (
        f"🏨 **環島中港通 "
        f"{' / '.join(active_regions)} "
        f"酒店套票快訊** | {TODAY_SHORT}\n\n"
    )

    sections = [_build_region_section(r, pkgs) for r, pkgs in grouped]
    body = "\n\n".join(sections)

    stats_footer = build_stats_footer(
        stats["pages_scanned"],
        stats["total_promos"],
        region_excluded,
        other_excluded,
        hotel_count,
    )

    footer = (
        f"\n\n━━━━━━━━━━━━━━━━━━━━━━"
        f"\n{stats_footer}"
        f"\n━━━━━━━━━━━━━━━━━━━━━━"
        f"\n🔗 查閱所有套票 → {BASE_URL}"
    )

    summary_line = (
        f"\n\n✅ 共 {hotel_count} 個酒店套票 | "
        f"🚫 已排除 {region_excluded + other_excluded} 個其他優惠"
    )

    return header + body + summary_line + footer


# ─────────────────────────────────────────────────────────────────────────────
# Discord 發送
# ─────────────────────────────────────────────────────────────────────────────

def post_to_discord(message: str) -> None:
    """透過 Incoming Webhook 向 Discord 發送訊息。

    - T9.6.5 `DRY_RUN=true` 環境變量：記錄但實際不發送
    - T9.6.1 重試：`DISCORD_RETRY_MAX` 次，exponential backoff
    """
    if DRY_RUN:
        _log_event(
            "discord.dry_run",
            length=len(message),
            preview=message[:200],
        )
        print(
            f"[DRY_RUN] Discord 訊息（{len(message)} 字元）已記錄但未發送"
        )
        return

    if len(message) > 1950:
        message = message[:1947] + "..."

    payload = {
        "username": "🏨 酒店套票機器人",
        "content": message,
    }

    last_error: Exception | None = None
    for attempt in range(1, DISCORD_RETRY_MAX + 1):
        try:
            response = requests.post(
                WEBHOOK_URL, json=payload, timeout=10
            )
            response.raise_for_status()
            _log_event(
                "discord.sent",
                length=len(message),
                attempt=attempt,
            )
            print(
                f"[INFO] Discord 通知已發送（{len(message)} 字元，"
                f"attempt={attempt}）"
            )
            return
        except requests.RequestException as e:
            last_error = e
            wait = DISCORD_RETRY_BACKOFF ** attempt
            print(
                f"[WARN] Discord 發送失敗 "
                f"（attempt={attempt}/{DISCORD_RETRY_MAX}）：{e}。"
                f"等待 {wait:.1f}s 重試"
            )
            if attempt < DISCORD_RETRY_MAX:
                time.sleep(wait)

    _log_event(
        "discord.failed",
        attempts=DISCORD_RETRY_MAX,
        error=str(last_error),
    )
    raise last_error if last_error else RuntimeError(
        "Discord 發送失敗：未知錯誤"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[INFO] 啟動酒店套票監察系統（v1.3）— {TODAY_CN}")
    _log_event(
        "run.start",
        today_cn=TODAY_CN,
        dry_run=DRY_RUN,
        base_url=BASE_URL,
        include_regions=INCLUDE_REGIONS,
    )

    # 步驟 1：抓取 hotel_packages.php
    try:
        raw_text, all_promotions, pages_scanned = scrape_all_pages()
        print(
            f"[INFO] 已抓取 {len(raw_text):,} 字元，"
            f"共 {pages_scanned} 頁，"
            f"解析到 {len(all_promotions)} 張卡片"
        )
        _log_event(
            "scrape.complete",
            chars=len(raw_text),
            pages=pages_scanned,
            promos=len(all_promotions),
        )
    except Exception as e:
        _log_event("scrape.failed", error=str(e))
        post_to_discord(
            f"⚠️ **優惠監察機器人錯誤** | {TODAY_SHORT}\n"
            f"抓取失敗：`{e}`\n"
            f"請手動檢查 → {BASE_URL}"
        )
        return

    stats: dict = {
        "pages_scanned": pages_scanned,
        "total_promos": len(all_promotions),
        "region_excluded": 0,
        "other_excluded": 0,
    }

    # 步驟 2：變更偵測
    current_hash = compute_hash(raw_text)
    if current_hash == load_last_hash():
        stats_no_change = build_stats_footer(
            pages_scanned, len(all_promotions), 0, 0, 0
        )
        post_to_discord(
            f"ℹ️ **環島中港通 酒店套票** — "
            f"今日頁面無更新（{TODAY_SHORT}）\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{stats_no_change}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 查閱所有套票 → {BASE_URL}"
        )
        _log_event("run.no_change", pages=pages_scanned)
        print("[INFO] 無變更，提前退出。")
        return

    print("[INFO] 頁面內容已更新 — 進行地區 + 預篩選")

    # T9.6.3：promo diff（觀測變更）
    last_promos = load_last_promos()
    if last_promos or all_promotions:
        diff = compute_promo_diff(last_promos, all_promotions)
        _log_event(
            "scrape.diff",
            added=len(diff["added"]),
            removed=len(diff["removed"]),
            added_urls=diff["added"][:5],
            removed_urls=diff["removed"][:5],
        )

    # 步驟 3：程序化預篩選（地區 + 關鍵詞 + 過期 + 住宿白名單）
    if all_promotions:
        region_kept: list[dict] = []
        region_excluded = 0
        for p in all_promotions:
            if region_allowed(p):
                region_kept.append(p)
            else:
                region_excluded += 1
                print(f"[FILTER] 地區不符：{p.get('title', '')[:40]}")

        stats["region_excluded"] = region_excluded
        print(f"[INFO] 地區過濾：{len(region_kept)} 張保留，{region_excluded} 張排除")

        if region_kept:
            filtered, other_excluded = prefilter(region_kept)
        else:
            filtered, other_excluded = [], 0
        stats["other_excluded"] = other_excluded
    else:
        print("[WARN] 未能解析卡片，回退為空結果")
        filtered = []
        region_excluded = 0
        other_excluded = 0
        stats["region_excluded"] = 0
        stats["other_excluded"] = 0

    print(
        f"[INFO] 預篩選：{len(filtered)} 張最終保留，"
        f"地區排除 {region_excluded}，其他排除 {other_excluded}"
    )

    # 步驟 4：並行抓取詳情頁，enrich 卡片
    if filtered:
        filtered = fetch_detail_pages(filtered)
        print(f"[INFO] 已豐富 {len(filtered)} 張卡片的詳情")

    # 步驟 5：發送 Discord
    try:
        message = build_discord_message(
            packages=filtered,
            stats=stats,
            region_excluded=region_excluded,
            other_excluded=other_excluded,
        )
        post_to_discord(message)
    except Exception as e:
        print(f"[ERROR] Discord 發送失敗：{e}")
        return

    # 步驟 6：儲存狀態
    save_hash(current_hash)
    save_last_promos(all_promotions)
    _log_event(
        "run.end",
        total_promos=len(all_promotions),
        region_excluded=region_excluded,
        other_excluded=other_excluded,
        hotel_count=len(filtered),
    )
    print("[INFO] 雜湊值已更新。執行完成。")


if __name__ == "__main__":
    main()
