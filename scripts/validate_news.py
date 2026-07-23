import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "data" / "news.json"
strict_details = "--strict-details" in sys.argv
foreign_sources = {"Reuters", "BBC", "Financial Times", "The Guardian", "TechCrunch", "The Real Deal", "PR Newswire"}
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
    for index, story in enumerate(data["stories"]):
        for key in ("title", "summary", "whyItMatters", "source", "category", "url"):
            if not story.get(key):
                raise ValueError(f"story {index} missing {key}")
        if story.get("category") == "投资市场":
            for key in ("market", "sentiment", "horizon", "riskNote"):
                if not story.get(key):
                    raise ValueError(f"investment story {index} missing {key}")
        if strict_details:
            detail = str(story.get("detailBody", "")).strip()
            facts = story.get("keyFacts") or []
            deep = bool(story.get("isTop"))
            min_detail, max_detail = (600, 1000) if deep else (400, 700)
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
    print(json.dumps({"valid": True, "stories": len(data["stories"])}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)
