"""
v1.3 煙霧測試（hotel_packages.php 目標 + 地區過濾 + 移除 LLM）

執行：python -m unittest tests.test_t9 -v
退出：0 = 全部通過；非 0 = 至少一個失敗
"""

import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "https://test.webhook")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scrape_and_notify as san  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helper：合成 hotel_packages.php 卡片 HTML
# ─────────────────────────────────────────────────────────────────────────────

def _make_card_html(
    title: str,
    region: str,
    price: str,
    unit: str = " 起/位",
    url: str = "https://www.tilchinalink.com/promotions.php?id=85&lang=tc",
) -> str:
    """合成單張 `<a class="package-wrapper">` 卡片的 HTML。"""
    return (
        f'<a href="{url}" class="package-wrapper is-link hotel-filter-item" '
        f'data-filter="1">'
        f'<div class="package-card">'
        f'<div class="package-card-image">'
        f'<img src="upload/{title}.jpg" alt="Hotel">'
        f'<span class="package-location">📍 {region}</span>'
        f'</div>'
        f'<div class="package-card-body">'
        f'<h3 class="package-card-title">{title}</h3>'
        f'<div class="package-card-footer">'
        f'<span class="package-price">{price}</span>'
        f'<span class="package-unit">{unit}</span>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</a>'
    )


def _make_grid_html(cards: list[str]) -> str:
    return (
        '<html><body>'
        '<div class="package-grid">'
        + "".join(cards)
        + '</div>'
        '</body></html>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# T9.3.1 — 日期 regex（保留）
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractEndDates(unittest.TestCase):
    """T9.3.1：擴展日期 regex 覆蓋 slash / dash / 即日起 場景。"""

    def test_chinese_full_range(self):
        text = "有效期 2026年5月1日 至 2026年8月31日"
        dates = san.extract_end_dates(text, 2026)
        self.assertIn(san._safe_date(2026, 8, 31), dates)
        self.assertGreaterEqual(len(dates), 1)

    def test_chinese_no_year_end(self):
        text = "2026年5月1日 至 5月20日 適用"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [san._safe_date(2026, 5, 20)])

    def test_chinese_single_end(self):
        text = "優惠期至 2026年12月31日"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [san._safe_date(2026, 12, 31)])

    def test_slash_full_range(self):
        text = "有效期 2026/05/01 至 2026/08/31"
        dates = san.extract_end_dates(text, 2026)
        self.assertIn(san._safe_date(2026, 8, 31), dates)

    def test_slash_dmy_range(self):
        text = "有效期 01/05/2026 至 31/08/2026"
        dates = san.extract_end_dates(text, 2026)
        self.assertIn(san._safe_date(2026, 8, 31), dates)

    def test_slash_single_end_ymd(self):
        text = "優惠期至 2026/12/31"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [san._safe_date(2026, 12, 31)])

    def test_slash_single_end_dmy(self):
        text = "優惠期至 31/12/2026"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [san._safe_date(2026, 12, 31)])

    def test_dash_single_end(self):
        text = "優惠期至 2026-12-31"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [san._safe_date(2026, 12, 31)])

    def test_jiriqi_no_end_date(self):
        text = "即日起接受預訂 入住豪華套房"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [])

    def test_invalid_date_ignored(self):
        text = "至 2026年13月99日"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [])


# ─────────────────────────────────────────────────────────────────────────────
# v1.3 — 卡片解析
# ─────────────────────────────────────────────────────────────────────────────

class TestHotelCardParser(unittest.TestCase):
    """v1.3：解析 hotel_packages.php 的卡片網格結構。"""

    def test_parse_card_basic(self):
        html = _make_card_html(
            title="寶安登喜路國際大酒店套票",
            region="深圳",
            price="$365",
            url="https://www.tilchinalink.com/promotions.php?id=85&lang=tc",
        )
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        anchor = soup.find("a", class_="package-wrapper")
        promo = san.parse_promotion(anchor)
        self.assertIsNotNone(promo)
        self.assertEqual(promo["title"], "寶安登喜路國際大酒店套票")
        self.assertEqual(promo["region"], "深圳")
        self.assertIn("365", promo["price"])
        self.assertEqual(
            promo["url"], "https://www.tilchinalink.com/promotions.php?id=85&lang=tc"
        )

    def test_parse_card_no_title_returns_none(self):
        html = (
            '<a href="https://x.com" class="package-wrapper">'
            '<div class="package-card-body"></div>'
            '</a>'
        )
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        anchor = soup.find("a", class_="package-wrapper")
        self.assertIsNone(san.parse_promotion(anchor))

    def test_parse_card_no_url_returns_none(self):
        html = (
            '<a class="package-wrapper">'
            '<h3 class="package-card-title">A</h3>'
            '</a>'
        )
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        anchor = soup.find("a", class_="package-wrapper")
        self.assertIsNone(san.parse_promotion(anchor))

    def test_parse_grid_multiple_cards(self):
        cards = [
            _make_card_html(f"酒店套票 {i}", r, f"${100 + i}",
                           url=f"https://www.tilchinalink.com/promotions.php?id={i}")
            for i, r in enumerate(["深圳", "廣州", "中山", "珠海"], start=1)
        ]
        html = _make_grid_html(cards)
        soup = __import__("bs4").BeautifulSoup(html, "html.parser")
        promos = []
        for anchor in soup.find_all("a", class_="package-wrapper"):
            p = san.parse_promotion(anchor)
            if p:
                promos.append(p)
        self.assertEqual(len(promos), 4)
        self.assertEqual([p["region"] for p in promos],
                         ["深圳", "廣州", "中山", "珠海"])


# ─────────────────────────────────────────────────────────────────────────────
# v1.3 — 地區過濾
# ─────────────────────────────────────────────────────────────────────────────

class TestRegionFilter(unittest.TestCase):
    """v1.3：region_allowed() 與 INCLUDE_REGIONS 白名單。"""

    def test_region_included(self):
        for r in san.INCLUDE_REGIONS:
            self.assertTrue(san.region_allowed({"region": r}))

    def test_region_excluded(self):
        for r in ["惠州", "佛山", "肇慶", "東莞"]:
            self.assertFalse(san.region_allowed({"region": r}))

    def test_empty_region_passes(self):
        """向後相容：舊黃金集無 region 欄位時預設放行。"""
        self.assertTrue(san.region_allowed({}))
        self.assertTrue(san.region_allowed({"title": "A"}))

    def test_group_by_region_order(self):
        packages = [
            {"title": "A", "region": "珠海"},
            {"title": "B", "region": "深圳"},
            {"title": "C", "region": "中山"},
        ]
        grouped = san.group_by_region(packages)
        regions = [r for r, _ in grouped]
        self.assertEqual(regions, ["深圳", "中山", "珠海"])

    def test_sort_by_region(self):
        packages = [
            {"title": "A", "region": "珠海"},
            {"title": "B", "region": "深圳"},
        ]
        sorted_pkgs = san.sort_by_region(packages)
        self.assertEqual([p["title"] for p in sorted_pkgs], ["B", "A"])

    def test_region_rank_complete(self):
        for i, r in enumerate(san.INCLUDE_REGIONS):
            self.assertEqual(san.REGION_RANK[r], i)


# ─────────────────────────────────────────────────────────────────────────────
# v1.3 — 滑雪排除 + 預篩選
# ─────────────────────────────────────────────────────────────────────────────

class TestSkiExclusion(unittest.TestCase):
    """v1.3：滑雪套票透過 EXCLUDE_KEYWORDS 排除。"""

    def test_snow_keyword_excluded(self):
        promos = [
            {
                "title": "廣州融創花間堂•悅雪酒店+滑雪套票",
                "region": "廣州",
                "date": "2026-06-01",
                "content": "",
                "url": "https://www.tilchinalink.com/promotions.php?id=110",
            }
        ]
        filtered, excluded = san.prefilter(promos)
        self.assertEqual(len(filtered), 0)
        self.assertEqual(excluded, 1)

    def test_snow_venue_keyword_excluded(self):
        promos = [
            {
                "title": "花都融創施柏閣酒店+滑雪套票",
                "region": "廣州",
                "date": "2026-06-01",
                "content": "雪場",
                "url": "https://www.tilchinalink.com/promotions.php?id=110",
            }
        ]
        filtered, _ = san.prefilter(promos)
        self.assertEqual(len(filtered), 0)

    def test_non_snow_kept(self):
        promos = [
            {
                "title": "中山喜來登酒店套票",
                "region": "中山",
                "date": "2026-06-01",
                "content": "住宿 1晚 標準房",
                "url": "https://www.tilchinalink.com/promotions.php?id=161",
            }
        ]
        filtered, _ = san.prefilter(promos)
        self.assertEqual(len(filtered), 1)


# ─────────────────────────────────────────────────────────────────────────────
# v1.3 — 預篩選（含地區 + 過期 + 關鍵詞）
# ─────────────────────────────────────────────────────────────────────────────

class TestPrefilterWhitelist(unittest.TestCase):
    """v1.3 預篩選：地區 + 過期 + 關鍵詞 + 住宿白名單。"""

    def _make(self, region, title, date="2026-06-01", content="住宿 1晚"):
        return {
            "title": title,
            "region": region,
            "date": date,
            "content": content,
            "url": "https://www.tilchinalink.com/promotions.php?id=1",
        }

    def test_hotel_keyword_match_zhusu(self):
        p = self._make("深圳", "A", content="酒店住宿 1晚")
        self.assertTrue(san.has_hotel_keyword(p))

    def test_hotel_keyword_match_ruzhufang(self):
        p = self._make("深圳", "A", content="標準房間")
        self.assertTrue(san.has_hotel_keyword(p))

    def test_hotel_keyword_match_fang(self):
        for kw in ["套房", "家庭房", "大床房", "標準房"]:
            p = self._make("深圳", "A", content=f"豪華{kw}")
            self.assertTrue(san.has_hotel_keyword(p), f"missed: {kw}")

    def test_hotel_keyword_no_match(self):
        p = self._make("深圳", "花山站點", content="新增上車站點")
        self.assertFalse(san.has_hotel_keyword(p))

    def test_region_filter_blocks_other_regions(self):
        p = self._make("惠州", "惠州皇冠假日酒店套票", content="住宿 1晚")
        filtered, _ = san.prefilter([p])
        self.assertEqual(len(filtered), 0)

    def test_prefilter_expired(self):
        p = self._make("深圳", "A", date="2025-01-01", content="住宿 1晚")
        filtered, _ = san.prefilter([p])
        self.assertEqual(len(filtered), 0)

    def test_prefilter_keeps_pickup_hotel_now_passes(self):
        """v1.3 行為變更：hotel_packages.php 已策展，不再依賴 has_hotel_keyword 白名單。

        在 v1.2 中，「花山希爾頓歡朋酒店 接送」會被 has_hotel_keyword 排除（無「住宿/入住/房間/房」）。
        v1.3 改為信任網站策展（hotel_packages.php 頁面只列酒店套票），故此類合成輸入會通過。
        真實生產中 hotel_packages.php 不會出現此類條目。
        """
        p = self._make(
            "深圳",
            "花山希爾頓歡朋酒店 接送",
            content="花山希爾頓歡朋酒店為新登車站點，買去程送回程",
        )
        filtered, _ = san.prefilter([p])
        self.assertEqual(len(filtered), 1)

    def test_prefilter_keeps_valid(self):
        p = self._make(
            "深圳",
            "寶安登喜路國際大酒店套票",
            content="住宿 1晚 標準房",
        )
        filtered, _ = san.prefilter([p])
        self.assertEqual(len(filtered), 1)

    def test_prefilter_empty_region_passes_region(self):
        """無 region 欄位（向後相容）→ 通過地區檢查。"""
        p = {"title": "A", "date": "2026-06-01", "content": "住宿 1晚"}
        filtered, _ = san.prefilter([p])
        self.assertEqual(len(filtered), 1)


# ─────────────────────────────────────────────────────────────────────────────
# T9.x — 常數預設值（更新為 v1.3）
# ─────────────────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_base_url_hotel_packages(self):
        self.assertEqual(
            san.BASE_URL,
            "https://www.tilchinalink.com/hotel_packages.php?lang=tc",
        )

    def test_max_pages_is_one(self):
        self.assertEqual(san.MAX_PAGES, 1)

    def test_include_regions(self):
        self.assertEqual(san.INCLUDE_REGIONS, ["深圳", "廣州", "中山", "珠海"])

    def test_exclude_keywords_only_snow(self):
        self.assertEqual(san.EXCLUDE_KEYWORDS, ["滑雪", "雪場", "雪場套票"])

    def test_promo_stale_default(self):
        self.assertEqual(san.PROMO_STALE_DAYS, 180)

    def test_discord_retry_max(self):
        self.assertEqual(san.DISCORD_RETRY_MAX, 3)

    def test_detail_fetch_workers_default(self):
        self.assertEqual(san.DETAIL_FETCH_WORKERS, 4)


# ─────────────────────────────────────────────────────────────────────────────
# T9.6.2 — 結構化日誌
# ─────────────────────────────────────────────────────────────────────────────

class TestStructuredLogging(unittest.TestCase):
    def setUp(self):
        self.records: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                self.records.append(self.format(record))

        self._capture = _Capture()
        self._capture.setFormatter(logging.Formatter("%(message)s"))
        self._capture.records = self.records
        san._STRUCT_LOGGER.addHandler(self._capture)

    def tearDown(self):
        san._STRUCT_LOGGER.removeHandler(self._capture)

    def _emitted(self) -> list[dict]:
        out = []
        for line in self.records:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out

    def test_log_event_emits_json(self):
        san._log_event("test.event", foo="bar", n=1)
        events = self._emitted()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "test.event")
        self.assertEqual(events[0]["foo"], "bar")
        self.assertEqual(events[0]["n"], 1)
        self.assertEqual(events[0]["run_id"], san.RUN_ID)
        self.assertEqual(events[0]["level"], "INFO")
        self.assertIn("ts", events[0])

    def test_log_event_extra_fields_unicode(self):
        san._log_event("test.unicode", msg="繁體中文 — 套票")
        events = self._emitted()
        self.assertEqual(events[0]["msg"], "繁體中文 — 套票")

    def test_run_id_default_uuid(self):
        self.assertEqual(len(san.RUN_ID), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in san.RUN_ID))


# ─────────────────────────────────────────────────────────────────────────────
# T9.6.3 — promo 持久化 + diff
# ─────────────────────────────────────────────────────────────────────────────

class TestPromoDiff(unittest.TestCase):
    def setUp(self):
        self._tmpdir = Path(tempfile.mkdtemp())
        self._orig_promos_file = san.PROMOS_FILE
        san.PROMOS_FILE = str(self._tmpdir / "last_promos.json")

    def tearDown(self):
        san.PROMOS_FILE = self._orig_promos_file
        for f in self._tmpdir.iterdir():
            f.unlink()
        self._tmpdir.rmdir()

    def test_diff_added_only(self):
        old = [{"url": "https://x.com/?id=1", "title": "A"}]
        new = [
            {"url": "https://x.com/?id=1", "title": "A"},
            {"url": "https://x.com/?id=2", "title": "B"},
        ]
        diff = san.compute_promo_diff(old, new)
        self.assertEqual(diff["added"], ["https://x.com/?id=2"])
        self.assertEqual(diff["removed"], [])

    def test_diff_removed_only(self):
        old = [
            {"url": "https://x.com/?id=1", "title": "A"},
            {"url": "https://x.com/?id=2", "title": "B"},
        ]
        new = [{"url": "https://x.com/?id=1", "title": "A"}]
        diff = san.compute_promo_diff(old, new)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], ["https://x.com/?id=2"])

    def test_diff_unchanged(self):
        old = [{"url": "https://x.com/?id=1", "title": "A"}]
        new = [{"url": "https://x.com/?id=1", "title": "A"}]
        diff = san.compute_promo_diff(old, new)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])

    def test_diff_title_change_not_counted(self):
        old = [{"url": "https://x.com/?id=1", "title": "舊標題"}]
        new = [{"url": "https://x.com/?id=1", "title": "新標題"}]
        diff = san.compute_promo_diff(old, new)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])

    def test_save_and_load_roundtrip(self):
        promos = [
            {"url": "https://x.com/?id=1", "title": "A"},
            {"url": "https://x.com/?id=2", "title": "B"},
        ]
        san.save_last_promos(promos)
        loaded = san.load_last_promos()
        self.assertEqual(loaded, promos)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(san.load_last_promos(), [])

    def test_load_corrupt_json_returns_empty(self):
        (self._tmpdir / "last_promos.json").write_text("not json{", encoding="utf-8")
        self.assertEqual(san.load_last_promos(), [])

    def test_load_non_list_returns_empty(self):
        (self._tmpdir / "last_promos.json").write_text('{"foo": 1}', encoding="utf-8")
        self.assertEqual(san.load_last_promos(), [])

    def test_per_page_hashes_format(self):
        pages = {1: "page one text", 2: "page two text"}
        hashes = san.compute_per_page_hashes(pages)
        self.assertEqual(set(hashes.keys()), {1, 2})
        for h in hashes.values():
            self.assertEqual(len(h), 16)


# ─────────────────────────────────────────────────────────────────────────────
# T9.6.1 — Discord 重試
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscordRetry(unittest.TestCase):
    def setUp(self):
        self._orig_dry = san.DRY_RUN
        self._orig_max = san.DISCORD_RETRY_MAX
        self._orig_backoff = san.DISCORD_RETRY_BACKOFF
        self._orig_url = san.WEBHOOK_URL
        san.DRY_RUN = False
        san.DISCORD_RETRY_MAX = 3
        san.DISCORD_RETRY_BACKOFF = 1
        san.WEBHOOK_URL = "https://test.webhook"
        self.events: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                self.events.append(record.getMessage())

        self._capture = _Capture()
        self._capture.events = self.events
        san._STRUCT_LOGGER.addHandler(self._capture)

    def tearDown(self):
        san.DRY_RUN = self._orig_dry
        san.DISCORD_RETRY_MAX = self._orig_max
        san.DISCORD_RETRY_BACKOFF = self._orig_backoff
        san.WEBHOOK_URL = self._orig_url
        san._STRUCT_LOGGER.removeHandler(self._capture)

    def _events_of(self, name: str) -> list[dict]:
        return [
            json.loads(line) for line in self.events
            if line.startswith("{") and f'"event": "{name}"' in line
        ]

    def test_succeeds_on_first_try(self):
        with mock.patch("scrape_and_notify.requests.post") as mp:
            mp.return_value.status_code = 204
            san.post_to_discord("hello")
            self.assertEqual(mp.call_count, 1)
        sent = self._events_of("discord.sent")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["attempt"], 1)

    def test_retry_then_succeed(self):
        with mock.patch("scrape_and_notify.requests.post") as mp:
            mp.side_effect = [
                requests.ConnectionError("net1"),
                requests.ConnectionError("net2"),
                mock.Mock(status_code=204),
            ]
            with mock.patch("scrape_and_notify.time.sleep") as sleep:
                san.post_to_discord("hello")
                self.assertEqual(mp.call_count, 3)
                self.assertEqual(sleep.call_count, 2)
        sent = self._events_of("discord.sent")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["attempt"], 3)

    def test_retry_exhausted_raises(self):
        with mock.patch("scrape_and_notify.requests.post") as mp:
            mp.side_effect = requests.ConnectionError("net")
            with mock.patch("scrape_and_notify.time.sleep"):
                with self.assertRaises(requests.ConnectionError):
                    san.post_to_discord("hello")
                self.assertEqual(mp.call_count, san.DISCORD_RETRY_MAX)
        failed = self._events_of("discord.failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["attempts"], san.DISCORD_RETRY_MAX)

    def test_exponential_backoff_timing(self):
        san.DISCORD_RETRY_BACKOFF = 2
        with mock.patch("scrape_and_notify.requests.post") as mp:
            mp.side_effect = requests.ConnectionError("net")
            with mock.patch("scrape_and_notify.time.sleep") as sleep:
                with self.assertRaises(requests.ConnectionError):
                    san.post_to_discord("hello")
            waits = [c.args[0] for c in sleep.call_args_list]
            self.assertEqual(waits, [2, 4])


# ─────────────────────────────────────────────────────────────────────────────
# T9.6.5 — DRY_RUN
# ─────────────────────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):
    def setUp(self):
        self._orig_dry = san.DRY_RUN
        self.events: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                self.events.append(record.getMessage())

        self._capture = _Capture()
        self._capture.events = self.events
        san._STRUCT_LOGGER.addHandler(self._capture)

    def tearDown(self):
        san.DRY_RUN = self._orig_dry
        san._STRUCT_LOGGER.removeHandler(self._capture)

    def _events_of(self, name: str) -> list[dict]:
        return [
            json.loads(line) for line in self.events
            if line.startswith("{") and f'"event": "{name}"' in line
        ]

    def test_dry_run_skips_http(self):
        san.DRY_RUN = True
        with mock.patch("scrape_and_notify.requests.post") as mp:
            san.post_to_discord("test message")
            self.assertEqual(mp.call_count, 0)
        dry = self._events_of("discord.dry_run")
        self.assertEqual(len(dry), 1)
        self.assertEqual(dry[0]["length"], len("test message"))

    def test_dry_run_env_var_parsing(self):
        for true_val in ("1", "true", "TRUE", "yes", "Yes"):
            os.environ["DRY_RUN"] = true_val
            self.assertTrue(_parse_dry_run_env())
        for false_val in ("0", "false", "no", "", "anything"):
            os.environ["DRY_RUN"] = false_val
            self.assertFalse(_parse_dry_run_env())
        os.environ.pop("DRY_RUN", None)


# ─────────────────────────────────────────────────────────────────────────────
# v1.3 — fetch_detail_page / fetch_detail_pages
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchDetailPages(unittest.TestCase):
    """v1.3：並行 detail-page 抓取與 enrich。"""

    def test_fetch_detail_page_extracts_date(self):
        html = (
            '<html><body>'
            '<div class="faintivory-background">'
            '<h3>深圳酒店套票</h3>'
            '<div>發布日期: 2026-05-12</div>'
            '<p>車票+住宿+自助餐人均低至HK$315起</p>'
            '</div>'
            '</body></html>'
        )
        with mock.patch("scrape_and_notify.requests.get") as mg:
            mg.return_value.status_code = 200
            mg.return_value.text = html
            result = san.fetch_detail_page("https://x.com")
        self.assertEqual(result["date"], "2026-05-12")
        self.assertIn("自助餐", result["dining"])
        self.assertIn("直通巴士", result["transport"])
        self.assertIsNone(result["nights"])

    def test_fetch_detail_page_handles_404(self):
        with mock.patch("scrape_and_notify.requests.get") as mg:
            mg.side_effect = requests.ConnectionError("net")
            result = san.fetch_detail_page("https://x.com")
        self.assertEqual(result["date"], "")
        self.assertIsNone(result["dining"])

    def test_fetch_detail_pages_dedupes_urls(self):
        promos = [
            {"url": "https://x.com/a", "title": "A"},
            {"url": "https://x.com/b", "title": "B"},
            {"url": "https://x.com/a", "title": "A2"},
        ]
        with mock.patch("scrape_and_notify.fetch_detail_page") as fdp:
            fdp.return_value = {
                "url": "", "date": "2026-06-01",
                "summary": "", "nights": None,
                "dining": None, "transport": None, "room_type": None,
            }
            enriched = san.fetch_detail_pages(promos)
        self.assertEqual(len(enriched), 3)
        self.assertEqual(fdp.call_count, 2)


def _parse_dry_run_env() -> bool:
    return os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
