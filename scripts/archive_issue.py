"""Save the current news edition as an immutable dated archive."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "data" / "news.json"
ARCHIVE_DIR = ROOT / "data" / "archive"
INDEX = ARCHIVE_DIR / "index.json"


def date_key(label: str) -> str:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", label)
    if not match:
        raise ValueError(f"cannot parse dateLabel: {label}")
    year, month, day = map(int, match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def main() -> None:
    data = json.loads(CURRENT.read_text(encoding="utf-8"))
    key = date_key(data["dateLabel"])
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{key}.json"
    archive_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    entries = []
    if INDEX.exists():
        entries = json.loads(INDEX.read_text(encoding="utf-8")).get("issues", [])
    entry = {
        "date": key,
        "dateLabel": data["dateLabel"],
        "issue": data["issue"],
        "statusLabel": data["statusLabel"],
        "storyCount": len(data["stories"]),
        "insightTitle": data["dailyInsight"]["title"],
    }
    entries = [item for item in entries if item.get("date") != key]
    entries.append(entry)
    entries.sort(key=lambda item: item["date"], reverse=True)
    INDEX.write_text(json.dumps({"issues": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"archive": str(archive_path), "issues": len(entries)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
