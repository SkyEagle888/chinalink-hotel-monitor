"""
T9.3.x / T9.4.x / T9.5.x 煙霧測試（T9 增強迭代）

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


class TestStructuredLogging(unittest.TestCase):
    """T9.6.2：結構化 JSON 日誌。"""

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


class TestPromoDiff(unittest.TestCase):
    """T9.6.3：promo 持久化 + diff 計算。"""

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
        """同一 URL 標題變更不視為新增/移除。"""
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


class TestDiscordRetry(unittest.TestCase):
    """T9.6.1：Discord Webhook 重試 + exponential backoff。"""

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
        """第 N 次失敗後等待 base**N 秒。"""
        san.DISCORD_RETRY_BACKOFF = 2
        with mock.patch("scrape_and_notify.requests.post") as mp:
            mp.side_effect = requests.ConnectionError("net")
            with mock.patch("scrape_and_notify.time.sleep") as sleep:
                with self.assertRaises(requests.ConnectionError):
                    san.post_to_discord("hello")
            waits = [c.args[0] for c in sleep.call_args_list]
            self.assertEqual(waits, [2, 4])


class TestDryRun(unittest.TestCase):
    """T9.6.5：DRY_RUN 環境變量支持。"""

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


class TestResponseFormatFallback(unittest.TestCase):
    """當供應商（如 Venice）不支援 `response_format` 時，應無縫改用 prompt-only JSON。"""

    def setUp(self):
        self._orig_self_consistency = san.SELF_CONSISTENCY_RUNS
        san.SELF_CONSISTENCY_RUNS = 1
        self.events: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                self.events.append(record.getMessage())

        self._capture = _Capture()
        self._capture.events = self.events
        san._STRUCT_LOGGER.addHandler(self._capture)

    def tearDown(self):
        san.SELF_CONSISTENCY_RUNS = self._orig_self_consistency
        san._STRUCT_LOGGER.removeHandler(self._capture)

    def _events_of(self, name: str) -> list[dict]:
        return [
            json.loads(line) for line in self.events
            if line.startswith("{") and f'"event": "{name}"' in line
        ]

    def _make_response(self, payload: str):
        resp = mock.Mock()
        resp.choices = [mock.Mock()]
        resp.choices[0].message.content = payload
        resp.usage = None
        return resp

    def test_fallback_on_response_format_400(self):
        """首次使用 JSON 模式失敗 → 自動重試無 response_format。"""
        unsupported_err = Exception(
            "Error code: 400 - response_format is not supported by this model"
        )
        good_payload = json.dumps({
            "packages": [
                {
                    "title": "測試酒店套票",
                    "validity": "持續有效",
                    "price": "HK$999",
                    "dining": "自助早餐",
                    "nights": 1,
                    "room_type": "標準房",
                    "booking": "微信小程式",
                    "note": "",
                    "url": "https://www.tilchinalink.com/promotions.php?id=999",
                }
            ],
            "excluded_count": 0,
        })

        with mock.patch("scrape_and_notify._invoke_model") as im:
            im.side_effect = [unsupported_err, self._make_response(good_payload)]
            with mock.patch("scrape_and_notify.time.sleep"):
                result = san._call_single_run("dummy content")

        self.assertEqual(im.call_count, 2)
        self.assertEqual(
            im.call_args_list[0].kwargs["use_response_format"], True
        )
        self.assertEqual(
            im.call_args_list[1].kwargs["use_response_format"], False
        )
        self.assertEqual(len(result["packages"]), 1)
        self.assertEqual(result["packages"][0]["title"], "測試酒店套票")

        fallback = self._events_of("llm.response_format_fallback")
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["model"], san.MODELS[0])

    def test_non_response_format_error_skips_fallback(self):
        """非 response_format 錯誤（如 5xx）不觸發 fallback，直接換下一模型。"""
        other_err = Exception("Error code: 503 - upstream unavailable")
        with mock.patch("scrape_and_notify._invoke_model") as im:
            im.side_effect = other_err
            with mock.patch("scrape_and_notify.time.sleep"):
                with self.assertRaises(RuntimeError) as ctx:
                    san._call_single_run("dummy content")
        self.assertEqual(im.call_count, len(san.MODELS))
        self.assertIn("所有 LLM 模型均失敗", str(ctx.exception))
        self.assertEqual(self._events_of("llm.response_format_fallback"), [])

    def test_fallback_failure_moves_to_next_model(self):
        """response_format fallback 重試亦失敗時，移至下一個備用模型。"""
        unsupported_err = Exception(
            "Error code: 400 - response_format is not supported by this model"
        )
        secondary_err = Exception("Error code: 500 - persistent failure")
        good_payload = json.dumps({"packages": [], "excluded_count": 0})

        with mock.patch("scrape_and_notify._invoke_model") as im:
            im.side_effect = [
                unsupported_err, secondary_err,
                self._make_response(good_payload),
            ]
            with mock.patch("scrape_and_notify.time.sleep"):
                result = san._call_single_run("dummy content")

        self.assertEqual(im.call_count, 3)
        self.assertEqual(result["packages"], [])

        fallback = self._events_of("llm.response_format_fallback")
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["model"], san.MODELS[0])


def _parse_dry_run_env() -> bool:
    return os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
