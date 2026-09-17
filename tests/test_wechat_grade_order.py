import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_wechat_article


class WeChatGradeOrderTests(unittest.TestCase):
    def test_editorial_priority_controls_order_within_grade(self):
        first = {"editorialGrade": "A", "editorialPriority": 1, "title": "重要财报"}
        later = {"editorialGrade": "A", "editorialPriority": 2, "title": "新车发布、销量、交付、利润、现金流"}
        self.assertGreater(
            generate_wechat_article.focus_score(first),
            generate_wechat_article.focus_score(later),
        )

    def test_editorial_grade_strictly_outranks_keyword_score(self):
        s_story = {
            "editorialGrade": "S",
            "title": "重大资产重组进入公告阶段",
            "summary": "交易方案仍待披露。",
            "newsBrief": "公司公告了一项重大资产重组，具体标的、估值与整合安排仍待后续正式预案披露。",
            "watchMetrics": ["交易估值"],
        }
        a_story = {
            "editorialGrade": "A",
            "title": "特斯拉发布新车并公布销量交付与利润",
            "summary": "新车、电池、自动驾驶、销量、交付、营收、利润率和经营现金流均有披露。",
            "newsBrief": "特斯拉发布新车，披露电池、智能驾驶、销量、交付、营收、净利润、毛利率、经营现金流、自由现金流和库存。",
            "watchMetrics": ["销量", "交付", "营收", "净利润"],
        }

        self.assertGreater(
            generate_wechat_article.focus_score(s_story),
            generate_wechat_article.focus_score(a_story),
        )


if __name__ == "__main__":
    unittest.main()
