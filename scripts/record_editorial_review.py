"""Record the human editorial gate after the shortlist has been reviewed."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "runtime" / "wechat_news.json"
CN_TZ = timezone(timedelta(hours=8))


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    stories = data.get("stories", [])
    if len(stories) < 11:
        raise ValueError("公众号条目少于11条")
    if any("\ufffd" in json.dumps(story, ensure_ascii=False) for story in stories):
        raise ValueError("公众号内容含乱码替换字符")
    if any(not story.get("newsBrief") or not story.get("whyItMatters") for story in stories):
        raise ValueError("公众号内容缺少事实或观察")
    data["editorialReview"] = {
        "status": "passed",
        "reviewedAt": datetime.now(CN_TZ).isoformat(),
        "method": "shortlist quality, source, freshness and duplicate review",
    }
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stories": len(stories), "status": "passed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
