"""Build an automotive-only WeChat edition independently of the website brief."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import prepare_daily_issue as daily

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "runtime" / "candidates.json"
OUTPUT = ROOT / "runtime" / "wechat_news.json"


def fresh(item: dict, now: datetime) -> bool:
    title = item.get("titleOriginal", "")
    if re.search(r"(?:201\d|202[0-5])年?", title):
        return False
    months = {int(value) for value in re.findall(r"(?<!\d)(1[0-2]|[1-9])月", title)}
    allowed = {now.month, 12 if now.month == 1 else now.month - 1}
    return not months or bool(months & allowed)


def choose(pool: list[dict], limit: int, topic_coverage: bool) -> list[dict]:
    ranked = sorted(pool, key=daily.score, reverse=True)
    ordered: list[dict] = []
    if topic_coverage:
        for topic in ("data", "smart", "vehicle", "supply", "industry"):
            candidate = next((item for item in ranked if daily.auto_subtopic(item) == topic and item not in ordered), None)
            if candidate:
                ordered.append(candidate)
    ordered.extend(item for item in ranked if item not in ordered)
    selected: list[dict] = []
    for item in ordered:
        if daily.too_similar(item, selected):
            continue
        if sum(existing["sourceHint"] == item["sourceHint"] for existing in selected) >= 2:
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    if len(selected) < limit:
        raise ValueError(f"not enough independent WeChat automotive candidates: {len(selected)}/{limit}")
    return selected


def main() -> None:
    now = datetime.now(daily.CN_TZ)
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", payload)
    valid_sources = daily.FOREIGN | daily.DOMESTIC | {"重点车企"}
    pool = [
        item for item in candidates
        if item.get("sourceHint") in valid_sources
        and item.get("categoryHint") in {"汽车产业", "汽车金融"}
        and daily.automotive_relevant(item)
        and fresh(item, now)
    ]
    auto_pool = [item for item in pool if item["categoryHint"] == "汽车产业"]
    finance_pool = [item for item in pool if item["categoryHint"] == "汽车金融"]
    domestic_auto = choose([item for item in auto_pool if item["sourceHint"] not in daily.FOREIGN], 7, True)
    foreign_auto = choose([item for item in auto_pool if item["sourceHint"] in daily.FOREIGN], 3, True)
    finance = choose([item for item in finance_pool if item["sourceHint"] not in daily.FOREIGN], 4, False)
    auto = domestic_auto + foreign_auto
    selected = auto + finance
    domestic_count = sum(item["sourceHint"] not in daily.FOREIGN for item in selected)
    domestic_ratio = domestic_count / len(selected)
    if not 0.75 <= domestic_ratio <= 0.85:
        raise ValueError(f"WeChat domestic source ratio outside target range: {domestic_count}/{len(selected)}")
    stories = [daily.make_story(item, index + 30) for index, item in enumerate(selected)]
    data = {
        "dateLabel": f"{now.year}年{now.month}月{now.day}日 星期{'一二三四五六日'[now.weekday()]}",
        "statusLabel": f"公众号选题完成 · {now:%H:%M}",
        "sources": sorted({story["source"] for story in stories}),
        "stories": stories,
    }
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "auto": len(auto), "finance": len(finance), "stories": len(stories), "domestic": domestic_count, "foreign": len(selected) - domestic_count, "domesticRatio": round(domestic_ratio, 3)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
