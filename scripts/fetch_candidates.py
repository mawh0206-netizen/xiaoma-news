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
BAIDU_HOT_URL = "https://top.baidu.com/board?tab=realtime"
BAIDU_AUTO_TERMS = (
    "汽车", "车企", "新能源车", "电动车", "小车", "轿车", "微型车",
    "代步车", "SUV", "特斯拉", "比亚迪", "蔚来", "小鹏", "理想",
    "小米汽车", "充电", "智驾", "自动驾驶", "车贷", "购车",
)

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
    ("重点车企", "汽车产业", "汽车集团 半年报 季报 业绩 营收 毛利率 净利润 经营现金流 单车收入"),
    ("重点车企", "汽车产业", "site:hkexnews.hk 汽车 年报 中期业绩 毛利率 现金流"),
    ("重点车企", "汽车产业", "site:sse.com.cn 汽车集团 年报 半年报 业绩"),
    ("重点车企", "汽车产业", "site:szse.cn 汽车集团 年报 半年报 业绩"),
    ("重点车企", "汽车产业", "automotive group quarterly half-year results revenue EBIT margin deliveries free cash flow"),
    ("重点车企", "汽车产业", "site:bmwgroup.com investor relations results automotive EBIT margin"),
    ("重点车企", "汽车产业", "site:volkswagen-group.com investors results operating margin deliveries"),
    ("重点车企", "汽车产业", "site:group.mercedes-benz.com investors results cars adjusted EBIT margin"),
    ("重点车企", "汽车产业", "site:stellantis.com investors financial results shipments industrial free cash flow"),
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


def normalize_publisher(value: str) -> str:
    publisher = clean(value)
    aliases = {
        "sina.cn": "新浪新闻",
        "新浪网": "新浪新闻",
        "bitauto.com": "易车",
        "autohome.com.cn": "汽车之家",
        "gasgoo.com": "盖世汽车",
    }
    return aliases.get(publisher.casefold(), aliases.get(publisher, publisher))


def candidate_quality(item: dict) -> bool:
    """Block obvious gaming, download and directory-page pollution globally."""
    title = str(item.get("titleOriginal", "")).lower()
    url = str(item.get("url", "")).lower()
    blocked_text = (
        "电子游戏", "博彩", "彩票网站", "体育投注", "开户链接",
        "官网版下载", "app下载官网", "pg电子", "电玩巴士", "配套采购/供应商",
        "汽车社区】", "互动平台-盖世汽车", "供应商_互动平台",
    )
    blocked_domains = ("tgbus.com",)
    return not any(term in title for term in blocked_text) and not any(domain in url for domain in blocked_domains)


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


def parse_feed(source: str, category: str, url: str, publisher_from_feed: bool = False) -> list[dict]:
    root = ET.fromstring(fetch(url))
    items = []
    for node in root.findall(".//item")[:30]:
        title = clean(node.findtext("title", ""))
        link = clean(node.findtext("link", ""))
        if not title or not link:
            continue
        desc = clean(node.findtext("description", ""))
        item = {
            "id": hashlib.sha1(f"{title}|{link}".encode()).hexdigest()[:16],
            "titleOriginal": title,
            "snippetOriginal": desc[:700],
            "url": link,
            "sourceHint": source,
            "categoryHint": category,
            "publishedAt": parse_date(node.findtext("pubDate", "")),
        }
        if publisher_from_feed:
            publisher = normalize_publisher(node.findtext("source", ""))
            if publisher:
                item["publisherHint"] = publisher
        items.append(item)
    return items


def google_news_url(query: str, locale: str) -> str:
    if locale == "zh":
        return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def fetch_baidu_hot_automotive() -> list[dict]:
    """Use Baidu Hot Search for discovery, then source stories from publishers."""
    page = fetch(BAIDU_HOT_URL).decode("utf-8", errors="replace")
    match = re.search(r"<!--s-data:(.*?)-->", page, re.S)
    if not match:
        raise ValueError("Baidu Hot Search data payload not found")
    payload = json.loads(match.group(1))
    cards = payload.get("data", {}).get("cards", [])
    hot_items = next((card.get("content", []) for card in cards if card.get("component") == "hotList"), [])
    discovered: list[dict] = []
    for position, hot_item in enumerate(hot_items[:50], 1):
        topic = clean(hot_item.get("word") or hot_item.get("query") or "")
        context = clean(hot_item.get("desc", ""))
        searchable = f"{topic} {context}".lower()
        if not topic or not any(term.lower() in searchable for term in BAIDU_AUTO_TERMS):
            continue
        results = parse_feed(
            "百度热搜",
            "汽车产业",
            google_news_url(f'"{topic}" when:2d', "zh"),
            publisher_from_feed=True,
        )
        for item in results[:5]:
            item.update({
                "discoverySource": "百度热搜",
                "hotRank": position,
                "hotScore": str(hot_item.get("hotScore", "")),
                "trendTitle": topic,
                "trendDescription": context[:500],
            })
            discovered.append(item)
    return discovered


def main() -> int:
    candidates, errors = [], []
    try:
        candidates.extend(fetch_baidu_hot_automotive())
    except Exception as exc:
        errors.append(f"百度热搜/汽车产业: {type(exc).__name__}: {exc}")
    for source, category, url in DIRECT_FEEDS:
        try:
            candidates.extend(parse_feed(source, category, url))
        except Exception as exc:
            errors.append(f"{source}/{category}: {type(exc).__name__}: {exc}")
    for source, category, query in SEARCHES:
        try:
            if category == "汽车金融":
                query = f"{query} when:7d"
            else:
                query = f"{query} when:2d"
            locale = "en" if source in {"Reuters", "Financial Times", "国际房地产", "Electrek", "InsideEVs", "Automotive News", "TechCrunch"} else "zh"
            candidates.extend(parse_feed(source, category, google_news_url(query, locale)))
        except Exception as exc:
            errors.append(f"{source}/{category}: {type(exc).__name__}: {exc}")

    unique = {}
    for item in candidates:
        if not candidate_quality(item):
            continue
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
