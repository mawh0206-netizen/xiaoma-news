"""Generate a WeChat-editor-friendly daily article from data/news.json."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "runtime" / "wechat_news.json"
OUTPUT = ROOT / "runtime" / "wechat_article.html"
PAYLOAD = ROOT / "runtime" / "wechat_payload.json"
SITE = "https://mawh0206-netizen.github.io/xiaoma-news"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


ARCHIVE_DATE = ""


def date_key(label: str) -> str:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", label)
    if not match:
        raise ValueError(f"cannot parse dateLabel: {label}")
    year, month, day = map(int, match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def detail_url(index: int) -> str:
    return f"{SITE}/detail.html?date={ARCHIVE_DATE}&story={index}"


def story_block(story: dict, index: int, number: int) -> str:
    metrics = extract_metrics(story)
    data_line = f'<p style="margin:0 0 12px;padding:10px 14px;background:#eef4f1;color:#1d6a55;font-size:14px;line-height:1.7;"><strong>数据线索：</strong>{esc(" · ".join(metrics))}</p>' if metrics else ""
    return f"""
    <section style="margin:0 0 28px;padding:0 0 25px;border-bottom:1px solid #e9e5dc;">
      <p style="margin:0 0 8px;color:#d94f36;font-size:13px;font-weight:700;letter-spacing:.06em;">{number:02d} · {esc(story['source'])} · {esc(story.get('publishedLabel', '今日'))}</p>
      <h3 style="margin:0 0 12px;color:#171a19;font-size:20px;line-height:1.5;font-weight:700;">{esc(story['title'])}</h3>
      <p style="margin:0 0 12px;color:#343936;font-size:16px;line-height:1.9;">{esc(story['summary'])}</p>
      {data_line}
      <p style="margin:0 0 13px;padding:12px 15px;background:#f5f3ee;border-left:3px solid #1d6a55;color:#4e5551;font-size:14px;line-height:1.8;"><strong style="color:#1d6a55;">产品经理观察：</strong>{esc(story['whyItMatters'])}</p>
      <p style="margin:0;color:#8a8f8b;font-size:12px;">资料来源：{esc(story['source'])}；详细资料与原文入口见文末“阅读原文”。</p>
    </section>"""


def bilingual_block(story: dict, index: int) -> str:
    return f"""
    <section style="margin:0 0 24px;padding:20px;background:#f7f5ef;border:1px solid #e3dfd5;">
      <p style="margin:0 0 8px;color:#d94f36;font-size:12px;font-weight:700;letter-spacing:.08em;">ENGLISH · {esc(story['source'])}</p>
      <h3 style="margin:0 0 13px;color:#171a19;font-family:Georgia,serif;font-size:19px;line-height:1.55;">{esc(story.get('originalTitle'))}</h3>
      <p style="margin:0 0 16px;color:#272b29;font-family:Georgia,serif;font-size:16px;line-height:1.9;">{esc(story.get('originalSummary'))}</p>
      <p style="margin:0 0 8px;padding-top:15px;border-top:1px solid #ddd8cc;color:#1d6a55;font-size:12px;font-weight:700;">中文对照翻译</p>
      <p style="margin:0;color:#4a504d;font-size:15px;line-height:1.9;">{esc(story.get('translatedSummary'))}</p>
      <p style="margin:13px 0 0;"><a href="{detail_url(index)}" style="color:#d94f36;font-size:13px;text-decoration:none;">进入站内中英对照详情 →</a></p>
    </section>"""


def section_title(number: str, title: str, subtitle: str) -> str:
    return f"""
    <section style="margin:42px 0 24px;">
      <p style="margin:0 0 7px;color:#d94f36;font-size:13px;font-weight:700;letter-spacing:.12em;">{number}</p>
      <h2 style="margin:0 0 8px;color:#171a19;font-size:26px;line-height:1.35;">{esc(title)}</h2>
      <p style="margin:0;color:#7a7f7b;font-size:14px;line-height:1.7;">{esc(subtitle)}</p>
    </section>"""


def select(stories: list[dict], categories: set[str], limit: int) -> list[tuple[int, dict]]:
    return [(i, s) for i, s in enumerate(stories) if s.get("category") in categories][:limit]


def focus_score(story: dict) -> int:
    text = f"{story.get('title', '')} {story.get('summary', '')}".lower()
    terms = {
        "新车": 8, "上市": 8, "首发": 7, "发布": 5, "车型": 6,
        "智能网联": 10, "车载ai": 10, "智能驾驶": 9, "自动驾驶": 9,
        "座舱": 8, "芯片": 7, "电池": 6, "充电": 5, "供应链": 7,
        "零部件": 6, "汽车金融": 8, "车贷": 8, "经销商": 6,
        "robotaxi": 9, "adas": 9, "connected-car": 9,
    }
    score = sum(weight for term, weight in terms.items() if term in text)
    data_terms = ("销量", "交付", "产量", "零售", "批发", "出口", "渗透率", "市场份额", "库存", "价格", "营收", "利润", "利润率", "现金流", "同比", "环比", "sales", "deliveries", "revenue", "margin", "inventory")
    score += min(36, sum(6 for term in data_terms if term in text))
    score += min(24, len(extract_metrics(story)) * 6)
    major_brands = ("特斯拉", "理想", "蔚来", "小鹏", "小米", "比亚迪", "tesla", "nio", "xpeng", "li auto", "xiaomi", "byd")
    major_events = ("上市", "首发", "发布", "交付", "销量", "财报", "利润", "召回", "降价", "涨价", "launch", "deliver", "earnings", "recall")
    if any(brand in text for brand in major_brands):
        score += 8
        if any(event in text for event in major_events):
            score += 24
    return score


def extract_metrics(story: dict) -> list[str]:
    text = f"{story.get('title', '')} {story.get('summary', '')}"
    values = re.findall(r"(?:约|超|近|达|增长|下降)?\s*\d+(?:\.\d+)?\s*(?:%|万亿元|亿元|万美元|亿美元|万元|万辆|万台|万套|万|亿元|美元|元|辆|台|家|倍)", text, flags=re.I)
    unique = []
    for value in values:
        cleaned = re.sub(r"\s+", "", value)
        if cleaned not in unique:
            unique.append(cleaned)
    return unique[:4]


def topic_groups(auto_items: list[tuple[int, dict]], finance_items: list[tuple[int, dict]]) -> list[tuple[str, str, str, list[tuple[int, dict]]]]:
    buckets: dict[str, list[tuple[int, dict]]] = {"数据与市场": [], "整车与品牌": [], "智能网联与车载AI": [], "供应链与产业经营": [], "汽车金融": []}
    subtitles = {
        "数据与市场": "销量、交付、渗透率、价格、库存与经营数据",
        "整车与品牌": "重磅产品、重点车企与整车经营变化",
        "智能网联与车载AI": "智能驾驶、车载软件、芯片与智能座舱",
        "供应链与产业经营": "电池、零部件、产能、成本与全球供应链",
        "汽车金融": "车贷、库存融资、经销商资金与风险管理",
    }
    for item in auto_items:
        story = item[1]
        text = f"{story.get('title', '')} {story.get('summary', '')}".lower()
        scores = {
            "数据与市场": len(extract_metrics(story)) * 5 + sum(term in text for term in ("销量", "交付", "产量", "零售", "出口", "渗透率", "库存", "利润", "同比", "环比")) * 4,
            "整车与品牌": sum(term in text for term in ("新车", "上市", "首发", "车型", "车企", "特斯拉", "理想", "蔚来", "小鹏", "小米", "比亚迪", "launch", "model")) * 4,
            "智能网联与车载AI": sum(term in text for term in ("智能网联", "车载ai", "智能驾驶", "自动驾驶", "座舱", "芯片", "robotaxi", "adas", "软件")) * 4,
            "供应链与产业经营": sum(term in text for term in ("供应链", "电池", "充电", "零部件", "产能", "工厂", "成本", "出口", "关税")) * 4,
        }
        topic = max(scores, key=scores.get)
        buckets[topic].append(item)
    buckets["汽车金融"] = finance_items
    limits = {"汽车金融": 4}
    ranked_groups = []
    for title, items in buckets.items():
        items = sorted(items, key=lambda item: focus_score(item[1]), reverse=True)[:limits.get(title, 10)]
        if items:
            group_score = max(focus_score(item[1]) for item in items)
            ranked_groups.append((group_score, title, subtitles[title], items))
    ranked_groups.sort(key=lambda group: group[0], reverse=True)
    return [(f"{index:02d}", title, subtitle, items) for index, (_, title, subtitle, items) in enumerate(ranked_groups, 1)]


def main() -> None:
    global ARCHIVE_DATE
    data = json.loads(DATA.read_text(encoding="utf-8"))
    ARCHIVE_DATE = date_key(data["dateLabel"])
    stories = data["stories"]
    auto_industry = [(i, s) for i, s in enumerate(stories) if s.get("category") == "汽车产业"]
    auto_finance = [(i, s) for i, s in enumerate(stories) if s.get("category") == "汽车金融"]
    groups = topic_groups(auto_industry, auto_finance)
    selected = [item for _, _, _, items in groups for item in items]
    if len(auto_industry) < 6 or len(auto_finance) < 3 or len(selected) < 8:
        raise ValueError("公众号汽车专刊缺少足够的汽车热点或汽车金融内容")
    lead_items = sorted(selected, key=lambda item: focus_score(item[1]), reverse=True)[:3]
    lead_title = lead_items[0][1]["title"]
    lead_body = "；".join(item[1]["summary"] for item in lead_items)

    body: list[str] = []
    body.append(f"""
      <header style="padding:34px 24px;background:#171a19;color:#fff;">
        <p style="margin:0 0 12px;color:#ef7059;font-size:13px;font-weight:700;letter-spacing:.14em;">小马儿YOUNG · 汽车产业观察</p>
        <h1 style="margin:0 0 14px;font-size:30px;line-height:1.3;">{esc(data['dateLabel'])} 汽车行业晨报</h1>
        <p style="margin:0;color:#c9ceca;font-size:15px;line-height:1.8;">聚焦智能网联、车载AI、整车与供应链、汽车金融，记录汽车产业每天值得关注的变化。</p>
      </header>
      <section style="margin:0;padding:26px 24px;background:#f5f3ee;border-bottom:1px solid #ddd8cc;">
        <p style="margin:0 0 8px;color:#d94f36;font-size:13px;font-weight:700;">今日汽车产业观察</p>
        <h2 style="margin:0 0 12px;color:#171a19;font-size:23px;line-height:1.45;">{esc(lead_title)}</h2>
        <p style="margin:0;color:#454b47;font-size:15px;line-height:1.9;">{esc(lead_body)}</p>
      </section>""")

    for number, title, subtitle, items in groups:
        body.append(section_title(number, title, subtitle))
        body.extend(story_block(s, i, n) for n, (i, s) in enumerate(items, 1))
    body.append(f"""
      <footer style="margin-top:42px;padding:28px 24px;background:#171a19;color:#d8dcd9;text-align:center;">
        <p style="margin:0 0 10px;color:#fff;font-size:20px;font-weight:700;">小马儿Young</p>
        <p style="margin:0 0 15px;font-size:13px;line-height:1.7;">汽车领域产品经理。关注智能网联与AI落地，持续精选汽车产业新闻，输出产品与行业观察。</p>
        <p style="margin:0 0 15px;color:#ef7059;font-size:14px;font-weight:700;">详细资料与新闻来源请点击文末“阅读原文”</p>
        <p style="margin:0;color:#909792;font-size:11px;line-height:1.65;">本文基于公开新闻资料整理，仅用于汽车行业信息交流，不构成投资、交易或其他专业建议。相关信息请以监管部门、企业公告及原媒体报道为准，版权归原作者与原媒体所有。</p>
      </footer>""")

    article = "".join(body)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(data['dateLabel'])} · 小马儿Young汽车行业晨报</title>
<style>body{{margin:0;background:#ecebe7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}}.toolbar{{position:sticky;top:0;z-index:5;padding:12px;text-align:center;background:#fff;border-bottom:1px solid #ddd}}button{{padding:10px 18px;border:0;border-radius:4px;background:#1d6a55;color:#fff;font-size:14px;cursor:pointer}}#wechat-article{{width:min(677px,100%);margin:24px auto;background:#fff;box-shadow:0 10px 35px rgba(0,0,0,.08)}}@media(max-width:700px){{#wechat-article{{margin:0 auto}}}}</style></head>
<body><div class="toolbar"><button id="copyButton">复制公众号正文</button> <span id="copyStatus"></span></div>
<main id="wechat-article">{article}</main>
<script>document.getElementById('copyButton').onclick=async()=>{{const article=document.getElementById('wechat-article');try{{await navigator.clipboard.write([new ClipboardItem({{'text/html':new Blob([article.innerHTML],{{type:'text/html'}}),'text/plain':new Blob([article.innerText],{{type:'text/plain'}})}})]);document.getElementById('copyStatus').textContent='已复制，可粘贴到公众号编辑器';}}catch(e){{const range=document.createRange();range.selectNode(article);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);document.execCommand('copy');document.getElementById('copyStatus').textContent='已复制';}}}};</script></body></html>"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document, encoding="utf-8")
    payload = {
        "title": f"{data['dateLabel']}｜汽车行业晨报",
        "author": "小马儿Young",
        "digest": f"聚焦智能网联、车载AI、整车供应链与汽车金融。今日关注：{lead_title}"[:120],
        "content": article,
        "content_source_url": f"{SITE}/archive.html?date={ARCHIVE_DATE}",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    PAYLOAD.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "payload": str(PAYLOAD), "selected": len(selected), "sections": [title for _, title, _, _ in groups]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
