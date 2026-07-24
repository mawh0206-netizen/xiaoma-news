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
    ("Reuters", "投资市场", "site:reuters.com markets stocks earnings Wall Street"),
    ("Reuters", "汽车产业", "site:reuters.com autos transportation EV"),
    ("Financial Times", "企业商业", "site:ft.com companies business"),
    ("Financial Times", "财经", "site:ft.com markets global economy"),
    ("Financial Times", "投资市场", "site:ft.com equities stocks markets earnings"),
    ("Financial Times", "汽车产业", "site:ft.com automobiles EV"),
    ("36氪", "科技", "site:36kr.com 科技 AI 企业"),
    ("第一财经", "财经", "site:yicai.com 财经 市场 公司"),
    ("第一财经", "投资市场", "site:yicai.com A股 港股 美股 上市公司 财报"),
    ("财联社", "财经", "site:cls.cn 财经 产业 公司"),
    ("财联社", "投资市场", "site:cls.cn A股 港股 美股 盘前 财报"),
    ("证券时报", "企业商业", "site:stcn.com 公司 产业 经营"),
    ("证券时报", "投资市场", "site:stcn.com A股 港股 上市公司 回购 财报"),
    ("澎湃新闻", "国际要闻", "site:thepaper.cn 国际 科技 财经"),
    ("界面新闻", "企业商业", "site:jiemian.com 公司 科技 商业"),
    ("经济观察报", "企业商业", "site:eeo.com.cn 企业 产业 财经"),
    ("盖世汽车", "汽车产业", "site:gasgoo.com 汽车 新能源 智能驾驶 供应链"),
    ("中国汽车报", "汽车产业", "site:cnautonews.com 汽车 行业 政策 出口"),
    ("中国汽车流通协会", "汽车产业", "site:cada.cn 汽车 流通 销量 库存"),
    ("汽车之家", "汽车产业", "site:autohome.com.cn 行业 新能源 车企"),
    ("工信部", "汽车产业", "site:miit.gov.cn 汽车 公告 智能网联 新能源 标准"),
    ("中国汽车工业协会", "汽车产业", "site:caam.org.cn 汽车 产销 新能源 出口"),
    ("乘联会", "汽车产业", "site:cpcaauto.com 汽车 销量 新能源 市场"),
    ("懂车帝", "汽车产业", "site:dongchedi.com 新车 上市 首发 智能驾驶 座舱"),
    ("新出行", "汽车产业", "site:xchuxing.com 新车 智能驾驶 座舱 新能源"),
    ("亿欧汽车", "汽车产业", "site:iyiou.com 汽车 智能网联 车载AI 供应链"),
    ("汽车商业评论", "汽车产业", "site:autobizreview.com 新车 汽车 供应链 智能驾驶"),
    ("中国汽车工业协会", "汽车产业", "site:caam.org.cn 月度 汽车 产量 销量 出口 新能源 渗透率"),
    ("乘联会", "汽车产业", "site:cpcaauto.com 月度 零售 批发 库存 渗透率 新能源"),
    ("盖世汽车", "汽车产业", "site:gasgoo.com 销量 交付量 出口 渗透率 利润率 库存 数据"),
    ("重点车企", "汽车产业", "特斯拉 理想 蔚来 小鹏 小米汽车 比亚迪 新车 上市 发布 交付 销量 财报"),
    ("Reuters", "汽车产业", "site:reuters.com Tesla BYD Nio Xpeng Li Auto Xiaomi vehicle sales deliveries earnings margin"),
    ("Electrek", "汽车产业", "site:electrek.co EV launch battery charging autonomous vehicle"),
    ("InsideEVs", "汽车产业", "site:insideevs.com new EV launch battery charging software"),
    ("Automotive News", "汽车产业", "site:autonews.com automaker vehicle launch supply chain software"),
    ("TechCrunch", "汽车产业", "site:techcrunch.com transportation mobility EV autonomous vehicle"),
    ("汽车金融", "汽车金融", "汽车金融 车贷 融资租赁 经销商 库存融资 汽车保险 残值"),
    ("第一财经", "汽车金融", "site:yicai.com 汽车金融 车贷 融资租赁"),
    ("财联社", "汽车金融", "site:cls.cn 汽车金融 车贷 银行 经销商"),
    ("证券时报", "汽车金融", "site:stcn.com 汽车金融 公司 贷款"),
    ("中国银行业协会", "汽车金融", "site:china-cba.net 汽车金融 车贷 风险"),
    ("零壹智库", "汽车金融", "site:01caijing.com 汽车金融 车贷 融资租赁"),
    ("中国房地产报", "房地产", "site:creb.com.cn 房地产 政策 市场"),
    ("中房网", "房地产", "site:cfnews.com.cn 房地产 市场 政策"),
    ("克而瑞", "房地产", "克而瑞 房地产 销售 土地 融资"),
    ("国内汽车综合", "汽车产业", "汽车 行业 新能源 车企 销量 政策"),
    ("国内房地产综合", "房地产", "中国 房地产 政策 成交 融资"),
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
            if category == "汽车产业":
                query = f"{query} when:2d"
            elif category == "汽车金融":
                query = f"{query} when:7d"
            locale = "en" if source in {"Reuters", "Financial Times", "国际房地产", "Electrek", "InsideEVs", "Automotive News", "TechCrunch"} else "zh"
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
