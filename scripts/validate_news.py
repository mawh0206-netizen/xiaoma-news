import json
import sys
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "data" / "news.json"
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
    print(json.dumps({"valid": True, "stories": len(data["stories"])}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)
