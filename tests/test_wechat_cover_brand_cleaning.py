import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_wechat_cover", ROOT / "scripts" / "generate_wechat_cover.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CoverBrandCleaningTests(unittest.TestCase):
    def test_preserves_euro_unit(self):
        story = {
            "title": "保时捷遭60亿欧元减值，豪华利润引擎变成重组压力",
            "source": "大众汽车集团/保时捷",
        }
        self.assertIn("60亿欧元", MODULE.cover_title(story))

    def test_removes_separated_media_suffix(self):
        story = {"title": "一条汽车新闻 - 亿欧", "source": "亿欧"}
        self.assertEqual("一条汽车新闻", MODULE.cover_title(story))

    def test_editorial_priority_controls_cover_lead_within_grade(self):
        priority_one = {
            "title": "重大政策落地",
            "summary": "政策正式生效。",
            "editorialGrade": "S",
            "editorialPriority": 1,
        }
        keyword_heavy = {
            "title": "销量利润交付创历史新高",
            "summary": "销量、利润、交付、市场份额与渗透率均增长。",
            "editorialGrade": "S",
            "editorialPriority": 2,
        }
        with patch.object(MODULE, "recent_cover_topics", return_value=[]):
            selected, _ = MODULE.select_lead({"stories": [keyword_heavy, priority_one]})
        self.assertIs(selected, priority_one)


if __name__ == "__main__":
    unittest.main()
