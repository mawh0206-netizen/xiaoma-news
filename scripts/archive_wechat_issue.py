"""Archive the independent WeChat automotive edition."""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "runtime" / "wechat_news.json"
ARCHIVE = ROOT / "data" / "wechat"
INDEX = ARCHIVE / "index.json"

def main() -> None:
    data = json.loads(CURRENT.read_text(encoding="utf-8"))
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", data["dateLabel"])
    if not match:
        raise ValueError(f"cannot parse date: {data['dateLabel']}")
    year, month, day = map(int, match.groups())
    key = f"{year:04d}-{month:02d}-{day:02d}"
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE / f"{key}.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entries = json.loads(INDEX.read_text(encoding="utf-8")).get("issues", []) if INDEX.exists() else []
    entry = {"date": key, "dateLabel": data["dateLabel"], "storyCount": len(data["stories"]), "statusLabel": data["statusLabel"]}
    entries = [item for item in entries if item.get("date") != key] + [entry]
    entries.sort(key=lambda item: item["date"], reverse=True)
    INDEX.write_text(json.dumps({"issues": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"archive": str(target), "stories": len(data["stories"])}, ensure_ascii=False))

if __name__ == "__main__":
    main()
