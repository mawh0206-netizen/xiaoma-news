"""Collect headline candidates from public RSS feeds; no article bodies are stored."""
from __future__ import annotations

import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runtime" / "candidates.json"
UA = "XiaomaNews/1.0 personal RSS reader"

DIRECT_FEEDS = [
    ("BBC", "国际要闻", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC", "科技", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("BBC", "企业商业", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("The Guardian", "AI", "https://www.theguardian.com/technology/artificialintelligenceai/rss"),
    ("The Guardian", "财经", "https://www.theguardian.com/business/rss"),
    ("TechCrunch", "AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("TechCrunch", "科技", "https://techcrunch.com/feed/"),
]

SEARCHES = [
    ("Reuters", "AI", "site:reuters.com AI artificial intelligence"),
    ("Reuters", "财经", "site:reuters.com markets economy business"),
    ("Reuters", "汽车产业", "site:reuters.com autos transportation EV"),
    ("Financial Times", "企业商业", "site:ft.com companies business"),
    ("Financial Times", "财经", "site:ft.com markets global economy"),
    ("Financial Times", "汽车产业", "site:ft.com automobiles EV"),
    ("国内汽车", "汽车产业", "汽车 行业 新能源 车企 销量 政策"),
    ("国内房地产", "房地产", "中国 房地产 政策 成交 融资"),
    ("国际房地产", "房地产", "global real estate housing market"),
]


def clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()


def parse_date(value: str) -> str:
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def parse_feed(source: str, category: str, url: str) -> list[dict]:
    root = ET.fromstring(fetch(url))
    items = []
    for node in root.findall(".//item")[:30]:
        title = clean(node.findtext("title", ""))
        link = clean(node.findtext("link", ""))
        if not title or not link:
            continue
        desc = clean(node.findtext("description", ""))
        items.append({
            "id": hashlib.sha1(f"{title}|{link}".encode()).hexdigest()[:16],
            "titleOriginal": title,
            "snippetOriginal": desc[:700],
            "url": link,
            "sourceHint": source,
            "categoryHint": category,
            "publishedAt": parse_date(node.findtext("pubDate", "")),
        })
    return items


def google_news_url(query: str, locale: str) -> str:
    if locale == "zh":
        return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def main() -> int:
    candidates, errors = [], []
    for source, category, url in DIRECT_FEEDS:
        try:
            candidates.extend(parse_feed(source, category, url))
        except Exception as exc:
            errors.append(f"{source}/{category}: {type(exc).__name__}: {exc}")
    for source, category, query in SEARCHES:
        try:
            locale = "zh" if source.startswith("国内") else "en"
            candidates.extend(parse_feed(source, category, google_news_url(query, locale)))
        except Exception as exc:
            errors.append(f"{source}/{category}: {type(exc).__name__}: {exc}")

    unique = {}
    for item in candidates:
        key = re.sub(r"\W+", "", item["titleOriginal"].lower())[:100]
        unique.setdefault(key, item)
    payload = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(unique),
        "errors": errors,
        "candidates": list(unique.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "count": len(unique), "errors": len(errors)}, ensure_ascii=False))
    return 0 if len(unique) >= 40 else 2


if __name__ == "__main__":
    sys.exit(main())
