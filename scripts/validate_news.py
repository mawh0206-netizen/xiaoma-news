import json
import sys
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "data" / "news.json"
strict_details = "--strict-details" in sys.argv
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"dateLabel", "issue", "statusLabel", "dailyInsight", "sources", "stories"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"missing keys: {sorted(missing)}")
    if len(data["stories"]) < 10:
        raise ValueError("at least 10 stories are required")
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
            if len(detail) < 400:
                raise ValueError(f"story {index} detailBody too short: {len(detail)} chars (minimum 400)")
            if len(facts) < 4:
                raise ValueError(f"story {index} has only {len(facts)} keyFacts (minimum 4)")
            if story.get("source") in {"Reuters", "BBC", "Financial Times", "The Guardian", "TechCrunch"}:
                if not story.get("originalTitle") or len(str(story.get("originalSummary", "")).split()) < 50:
                    raise ValueError(f"foreign story {index} missing sufficient bilingual source material")
    print(json.dumps({"valid": True, "stories": len(data["stories"])}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)
