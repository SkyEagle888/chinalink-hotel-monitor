"""
T9.3.x / T9.4.x / T9.5.x 煙霧測試（T9 增強迭代）

執行：python -m unittest tests.test_t9 -v
退出：0 = 全部通過；非 0 = 至少一個失敗
"""

import json
import os
import sys
import unittest
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "https://test.webhook")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scrape_and_notify as san  # noqa: E402


class TestExtractEndDates(unittest.TestCase):
    """T9.3.1：擴展日期 regex 覆蓋 slash / dash / 即日起 場景。"""

    def test_chinese_full_range(self):
        text = "有效期 2026年5月1日 至 2026年8月31日"
        dates = san.extract_end_dates(text, 2026)
        # Range pattern + single-end pattern both match — duplicates are
        # harmless; caller uses max(). Just verify the end date is present.
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
        """「即日起」不應被視為結束日期。"""
        text = "即日起接受預訂 入住豪華套房"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [])

    def test_invalid_date_ignored(self):
        text = "至 2026年13月99日"
        dates = san.extract_end_dates(text, 2026)
        self.assertEqual(dates, [])


class TestPrefilterWhitelist(unittest.TestCase):
    """T9.3.2：正向白名單 + T9.4.3 啟發式第二輪。"""

    def test_hotel_keyword_match_zhusu(self):
        p = {"title": "A", "content": "酒店住宿 1晚", "date": ""}
        self.assertTrue(san.has_hotel_keyword(p))

    def test_hotel_keyword_match_ruzhufang(self):
        p = {"title": "A", "content": "標準房間", "date": ""}
        self.assertTrue(san.has_hotel_keyword(p))

    def test_hotel_keyword_match_fang(self):
        """單字「房」應匹配（套房、家庭房、大床房 等）。"""
        for kw in ["套房", "家庭房", "大床房", "標準房"]:
            p = {"title": "A", "content": f"豪華{kw}", "date": ""}
            self.assertTrue(san.has_hotel_keyword(p), f"missed: {kw}")

    def test_hotel_keyword_no_match(self):
        p = {"title": "花山站點", "content": "新增上車站點", "date": ""}
        self.assertFalse(san.has_hotel_keyword(p))

    def test_prefilter_2nd_round_threshold(self):
        """候選 ≥ 3 且非住宿+餐飲雙命中 → 排除。"""
        promos = [
            {"title": "A", "content": "酒店住宿 1晚 純住宿", "date": "2026-06-01"},
            {"title": "B", "content": "酒店住宿 1晚 純住宿", "date": "2026-06-01"},
            {"title": "C", "content": "酒店住宿 1晚 純住宿", "date": "2026-06-01"},
            {"title": "D", "content": "酒店住宿 1晚 + 自助早餐", "date": "2026-06-01"},
        ]
        filtered, excluded = san.prefilter(promos)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "D")
        self.assertEqual(excluded, 3)

    def test_prefilter_2nd_round_below_threshold(self):
        """候選 < 3 → 不啟動第二輪。"""
        promos = [
            {"title": "A", "content": "酒店住宿 1晚 純住宿", "date": "2026-06-01"},
            {"title": "B", "content": "酒店住宿 1晚 + 自助早餐", "date": "2026-06-01"},
        ]
        filtered, _ = san.prefilter(promos)
        self.assertEqual(len(filtered), 2)

    def test_prefilter_exclude_keyword(self):
        p = {
            "title": "郭富城演唱會套票",
            "content": "酒店住宿 + 演唱會門票 + 早餐",
            "date": "2026-06-01",
        }
        filtered, excluded = san.prefilter([p])
        self.assertEqual(len(filtered), 0)
        self.assertEqual(excluded, 1)

    def test_prefilter_expired(self):
        """發布日期 > 180 天前且無結束日期 → 過期排除。"""
        p = {
            "title": "A",
            "content": "酒店住宿 + 自助早餐",
            "date": "2025-01-01",
        }
        filtered, _ = san.prefilter([p])
        self.assertEqual(len(filtered), 0)

    def test_prefilter_whitelist_blocks_pickup_hotel(self):
        """酒店名僅為上落車地點（無住宿關鍵字）→ 排除。"""
        p = {
            "title": "花山希爾頓歡朋酒店 接送",
            "content": "花山希爾頓歡朋酒店為新登車站點，買去程送回程",
            "date": "2026-06-01",
        }
        filtered, _ = san.prefilter([p])
        self.assertEqual(len(filtered), 0)


class TestUrlValidation(unittest.TestCase):
    """T9.3.3：輸出驗證層。"""

    def test_valid_urls(self):
        data = {
            "packages": [
                {"url": "https://www.tilchinalink.com/promotions.php?id=201"},
                {"url": "https://www.tilchinalink.com/promotions.php?id=205"},
            ],
            "excluded_count": 0,
        }
        self.assertEqual(san._validate_urls(data), [])

    def test_missing_url(self):
        data = {
            "packages": [{"url": "", "title": "A"}],
            "excluded_count": 0,
        }
        self.assertEqual(san._validate_urls(data), ["A"])

    def test_url_without_id(self):
        data = {
            "packages": [{"url": "https://example.com/foo", "title": "B"}],
            "excluded_count": 0,
        }
        self.assertEqual(san._validate_urls(data), ["B"])

    def test_drop_invalid(self):
        data = {
            "packages": [
                {"url": "https://x.com/p?id=1", "title": "ok"},
                {"url": "", "title": "bad"},
            ],
            "excluded_count": 0,
        }
        out = san._drop_invalid_urls(data)
        self.assertEqual(len(out["packages"]), 1)
        self.assertEqual(out["packages"][0]["title"], "ok")
        self.assertEqual(out["excluded_count"], 1)


class TestIntersectRuns(unittest.TestCase):
    """T9.5.3：self-consistency 交集邏輯。"""

    def test_intersection_common(self):
        runs = [
            {"packages": [
                {"url": "u1", "title": "A"},
                {"url": "u2", "title": "B"},
            ], "excluded_count": 0},
            {"packages": [
                {"url": "u1", "title": "A"},
                {"url": "u3", "title": "C"},
            ], "excluded_count": 1},
        ]
        result = san._intersect_runs(runs)
        urls = {p["url"] for p in result["packages"]}
        self.assertEqual(urls, {"u1"})
        self.assertEqual(result["excluded_count"], 1)

    def test_intersection_empty_fallback(self):
        """交集為空 → fallback 第一輪（避免 false negative）。"""
        runs = [
            {"packages": [{"url": "u1", "title": "A"}], "excluded_count": 0},
            {"packages": [{"url": "u2", "title": "B"}], "excluded_count": 0},
        ]
        result = san._intersect_runs(runs)
        self.assertEqual(len(result["packages"]), 1)
        self.assertEqual(result["packages"][0]["url"], "u1")

    def test_single_run(self):
        runs = [{"packages": [{"url": "u1"}], "excluded_count": 0}]
        result = san._intersect_runs(runs)
        self.assertEqual(len(result["packages"]), 1)

    def test_empty_runs(self):
        result = san._intersect_runs([])
        self.assertEqual(result["packages"], [])
        self.assertEqual(result["excluded_count"], 0)


class TestParseLlmJson(unittest.TestCase):
    """T9.2.2：JSON 解析容錯（已實作，本測試確保未來變更不破壞）。"""

    def test_well_formed(self):
        raw = json.dumps({
            "packages": [
                {
                    "title": "測試",
                    "validity": "持續有效",
                    "price": "HK$100",
                    "dining": "自助早餐",
                    "nights": 2,
                    "room_type": "標準房",
                    "booking": "微信",
                    "note": "備注",
                    "url": "https://x.com/p?id=1",
                }
            ],
            "excluded_count": 3,
        })
        out = san._parse_llm_json(raw)
        self.assertEqual(len(out["packages"]), 1)
        self.assertEqual(out["packages"][0]["nights"], 2)
        self.assertEqual(out["excluded_count"], 3)

    def test_missing_fields_default(self):
        out = san._parse_llm_json(json.dumps({"packages": [{}], "excluded_count": 0}))
        p = out["packages"][0]
        self.assertEqual(p["validity"], "持續有效")
        self.assertEqual(p["price"], "請查閱官網")
        self.assertEqual(p["nights"], 1)

    def test_invalid_json_raises(self):
        with self.assertRaises(RuntimeError):
            san._parse_llm_json("not json")

    def test_excluded_count_bool_rejected(self):
        out = san._parse_llm_json(
            json.dumps({"packages": [], "excluded_count": True})
        )
        self.assertEqual(out["excluded_count"], 0)


class TestConstants(unittest.TestCase):
    """T9.x 配置常數預設值驗證。"""

    def test_self_consistency_default(self):
        self.assertEqual(san.SELF_CONSISTENCY_RUNS, 2)

    def test_url_retry_default(self):
        self.assertEqual(san.URL_RETRY_LIMIT, 1)

    def test_heuristic_threshold(self):
        self.assertEqual(san.HEURISTIC_2ND_ROUND_THRESHOLD, 3)

    def test_hotel_keywords_include_fang(self):
        for kw in ["住宿", "入住", "房間", "房"]:
            self.assertIn(kw, san.HOTEL_KEYWORDS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
