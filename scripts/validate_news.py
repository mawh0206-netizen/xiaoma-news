import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "data" / "news.json"
archive_root = path.parent / "archive"
strict_details = "--strict-details" in sys.argv
foreign_sources = {"Reuters", "BBC", "Financial Times", "The Guardian", "TechCrunch", "The Real Deal", "PR Newswire", "Electrek", "InsideEVs", "Automotive News"}
domestic_sources = {"第一财经", "财联社", "证券时报", "36氪", "澎湃新闻", "盖世汽车", "中国汽车报", "中国汽车流通协会", "北汽汽车金融"}
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"dateLabel", "issue", "statusLabel", "dailyInsight", "sources", "stories"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"missing keys: {sorted(missing)}")
    if len(data["stories"]) < 10:
        raise ValueError("at least 10 stories are required")
    if strict_details:
        today = datetime.now(timezone(timedelta(hours=8)))
        expected_date = f"{today.year}年{today.month}月{today.day}日"
        if not str(data["dateLabel"]).startswith(expected_date):
            raise ValueError(f"dateLabel is not today in Beijing: {data['dateLabel']}")
        top = [story for story in data["stories"] if story.get("isTop")]
        if not 18 <= len(top) <= 22:
            raise ValueError(f"homepage requires about 20 stories, found {len(top)}")
        top_foreign = sum(story.get("source") in foreign_sources for story in top)
        if abs(top_foreign - (len(top) - top_foreign)) > 2:
            raise ValueError(f"homepage domestic/foreign split is unbalanced: {len(top)-top_foreign}/{top_foreign}")
        investments = [story for story in data["stories"] if story.get("category") == "投资市场"]
        if len(investments) < 12:
            raise ValueError(f"investment column requires at least 12 stories, found {len(investments)}")
        inv_foreign = sum(story.get("source") in foreign_sources for story in investments)
        if abs(inv_foreign - (len(investments) - inv_foreign)) > 2:
            raise ValueError(f"investment domestic/foreign split is unbalanced: {len(investments)-inv_foreign}/{inv_foreign}")
        historical_urls = set()
        for archive_path in archive_root.glob("*.json"):
            if archive_path.name == "index.json":
                continue
            try:
                archive_date = datetime.strptime(archive_path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if archive_date >= today.date():
                continue
            archive = json.loads(archive_path.read_text(encoding="utf-8"))
            for archived_story in archive.get("stories", []):
                historical_urls.update(
                    url
                    for url in (archived_story.get("url"), archived_story.get("aggregatorUrl"))
                    if url
                )
        current_urls = []
    for index, story in enumerate(data["stories"]):
        for key in ("title", "summary", "whyItMatters", "source", "category", "url"):
            if not story.get(key):
                raise ValueError(f"story {index} missing {key}")
        if story.get("category") == "投资市场":
            for key in ("market", "sentiment", "horizon", "riskNote"):
                if not story.get(key):
                    raise ValueError(f"investment story {index} missing {key}")
        if strict_details:
            published_value = str(story.get("publishedAt", "")).strip()
            if not published_value:
                raise ValueError(f"story {index} missing publishedAt")
            try:
                published = datetime.fromisoformat(published_value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"story {index} has invalid publishedAt: {published_value}") from exc
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            published = published.astimezone(today.tzinfo)
            age = today - published
            maximum_age = timedelta(days=7) if story.get("category") == "汽车金融" else timedelta(hours=48)
            if age < -timedelta(minutes=10) or age > maximum_age:
                raise ValueError(f"story {index} publishedAt outside freshness window: {published_value}")
            if published.date() == today.date():
                expected_label = f"今日 {published:%H:%M}"
            elif published.date() == (today - timedelta(days=1)).date():
                expected_label = f"昨日 {published:%H:%M}"
            else:
                expected_label = f"{published.month}月{published.day}日 {published:%H:%M}"
            if story.get("publishedLabel") != expected_label:
                raise ValueError(
                    f"story {index} publishedLabel mismatch: {story.get('publishedLabel')} != {expected_label}"
                )
            story_urls = [url for url in (story.get("url"), story.get("aggregatorUrl")) if url]
            repeated = historical_urls.intersection(story_urls)
            if repeated:
                raise ValueError(f"story {index} repeats archived URL: {sorted(repeated)[0]}")
            current_urls.extend(story_urls)
            detail = str(story.get("detailBody", "")).strip()
            facts = story.get("keyFacts") or []
            deep = bool(story.get("isTop"))
            min_detail, max_detail = (300, 1000) if deep else (250, 1000)
            min_facts = 6 if deep else 4
            if not min_detail <= len(detail) <= max_detail:
                raise ValueError(f"story {index} detailBody length {len(detail)} outside {min_detail}-{max_detail}")
            if len(facts) < min_facts:
                raise ValueError(f"story {index} has only {len(facts)} keyFacts (minimum {min_facts})")
            paragraphs = [p.strip() for p in detail.split("\n") if p.strip()]
            normalized_paragraphs = [re.sub(r"\s+", "", p) for p in paragraphs]
            if len(normalized_paragraphs) != len(set(normalized_paragraphs)):
                raise ValueError(f"story {index} detailBody contains duplicate paragraphs")
            if story.get("source") in foreign_sources:
                word_count = len(str(story.get("originalSummary", "")).split())
                if not story.get("originalTitle") or not 80 <= word_count <= 150:
                    raise ValueError(f"foreign story {index} missing sufficient bilingual source material")
                if not story.get("translatedSummary"):
                    raise ValueError(f"foreign story {index} missing line-aligned Chinese translation")
                en_sentences = len([x for x in re.split(r"(?<=[.!?])\s+", story["originalSummary"].strip()) if x])
                zh_sentences = len([x for x in re.split(r"(?<=[。！？])", story["translatedSummary"].strip()) if x.strip()])
                if en_sentences != zh_sentences:
                    raise ValueError(f"foreign story {index} bilingual sentence count differs: {en_sentences}/{zh_sentences}")
    if strict_details and len(current_urls) != len(set(current_urls)):
        raise ValueError("current edition contains duplicate direct or aggregator URLs")
    print(json.dumps({"valid": True, "stories": len(data["stories"])}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)
