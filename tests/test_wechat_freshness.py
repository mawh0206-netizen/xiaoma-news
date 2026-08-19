import unittest
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import prepare_daily_issue as daily
import prepare_wechat_issue


class WeChatFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 19, 7, 40, tzinfo=daily.CN_TZ)

    @staticmethod
    def item(published_at: str) -> dict:
        return {"publishedAt": published_at}

    def test_accepts_today(self):
        self.assertTrue(prepare_wechat_issue.within_current_or_previous_day(
            self.item("2026-08-19T00:01:00+08:00"), self.now
        ))

    def test_accepts_previous_calendar_day(self):
        self.assertTrue(prepare_wechat_issue.within_current_or_previous_day(
            self.item("2026-08-18T00:00:00+08:00"), self.now
        ))

    def test_rejects_two_days_old_even_if_under_48_hours(self):
        self.assertFalse(prepare_wechat_issue.within_current_or_previous_day(
            self.item("2026-08-17T23:59:59+08:00"), self.now
        ))

    def test_converts_to_beijing_date_before_filtering(self):
        self.assertTrue(prepare_wechat_issue.within_current_or_previous_day(
            self.item("2026-08-17T16:00:00+00:00"), self.now
        ))

    def test_rejects_missing_or_invalid_time(self):
        self.assertFalse(prepare_wechat_issue.within_current_or_previous_day({}, self.now))
        self.assertFalse(prepare_wechat_issue.within_current_or_previous_day(
            self.item("not-a-time"), self.now
        ))


if __name__ == "__main__":
    unittest.main()
