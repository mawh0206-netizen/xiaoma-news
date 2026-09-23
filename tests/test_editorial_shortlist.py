import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import prepare_wechat_issue as wechat


def candidate(title: str, source: str, url: str, snippet: str = "正文摘要包含可核验的汽车行业事实和数据。") -> dict:
    return {
        "id": url.rsplit("/", 1)[-1],
        "titleOriginal": title,
        "snippetOriginal": snippet,
        "sourceHint": source,
        "categoryHint": "汽车产业",
        "publishedAt": "2026-09-23T08:00:00+08:00",
        "url": url,
    }


class EditorialShortlistTests(unittest.TestCase):
    def test_authoritative_financial_story_outranks_promotional_story(self):
        financial = candidate(
            "某车企半年报：汽车业务利润下滑并下调现金流指引",
            "重点车企",
            "https://example.com/financial",
        )
        promotional = candidate(
            "品牌峰会重磅来袭，科技赋能新车亮相",
            "汽车之家",
            "https://example.com/promo",
        )
        self.assertGreater(
            wechat.editorial_candidate_score(financial),
            wechat.editorial_candidate_score(promotional),
        )

    def test_deduplicates_same_event_across_publishers(self):
        first = candidate(
            "比亚迪因制动风险召回18万辆汽车",
            "工信部",
            "https://example.com/official",
        )
        duplicate = candidate(
            "比亚迪因制动风险召回18万辆汽车 - 汽车之家",
            "汽车之家",
            "https://example.com/repost",
        )
        result = wechat.build_editorial_shortlist([duplicate, first], limit=10)
        self.assertEqual(1, len(result))
        self.assertEqual("工信部", result[0]["sourceHint"])

    def test_caps_shortlist_and_source_concentration(self):
        pool = [
            candidate(
                f"车企{i}公布销量与交付数据{i}万辆",
                "Reuters",
                f"https://example.com/reuters/{i}",
            )
            for i in range(8)
        ]
        pool.extend(
            candidate(
                f"监管部门发布汽车安全新规第{i}项",
                "工信部" if i % 2 == 0 else "中国汽车工业协会",
                f"https://example.com/official/{i}",
            )
            for i in range(8)
        )
        result = wechat.build_editorial_shortlist(pool, limit=8)
        self.assertLessEqual(len(result), 8)
        self.assertLessEqual(sum(item["sourceHint"] == "Reuters" for item in result), 4)

    def test_rejects_newsletter_review_and_test_drive_formats(self):
        pool = [
            candidate("Daily 5 newsletter: today's auto stories", "Reuters", "https://example.com/daily"),
            candidate("New EV review: I drove it for a week", "Reuters", "https://example.com/review"),
            candidate("新车深度试驾：城市道路体验", "汽车之家", "https://example.com/test-drive"),
            candidate("监管部门发布汽车安全新规并公布实施日期", "工信部", "https://example.com/rule"),
        ]
        result = wechat.build_editorial_shortlist(pool, limit=10)
        self.assertEqual(1, len(result))
        self.assertEqual("工信部", result[0]["sourceHint"])


if __name__ == "__main__":
    unittest.main()
