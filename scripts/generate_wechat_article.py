"""Generate a WeChat-editor-friendly daily article from data/news.json."""
from __future__ import annotations

import html
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from generate_wechat_cover import render_cover

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
    return f"{SITE}/detail.html?edition=wechat&date={ARCHIVE_DATE}&story={index}"


def redundant_summary(story: dict) -> bool:
    """Hide feed snippets that merely repeat the headline with punctuation changes."""
    def normalized(value: object) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())

    title = normalized(story.get("title"))
    summary = normalized(story.get("summary"))
    if not summary:
        return True
    return bool(title) and SequenceMatcher(None, title, summary).ratio() >= 0.82


def story_block(story: dict, index: int, section_number: str, number: int) -> str:
    metrics = extract_metrics(story)
    data_line = f'<p style="margin:0 0 10px;padding:8px 12px;background:#eef4f1;color:#1d6a55;font-size:14px;line-height:1.65;"><strong>数据线索：</strong>{esc(" · ".join(metrics))}</p>' if metrics else ""
    news_brief = str(story.get("newsBrief") or "").strip()
    if len(news_brief) < 55:
        raise ValueError(f"公众号新闻事实不足：{story.get('title', '')}")
    brief_origin = esc(story.get("newsBriefSource") or "公开信息")
    summary_line = (
        '<div style="margin:0 0 12px;padding:12px 14px;background:#fff;border:1px solid #e9e5dc;">'
        f'<p style="margin:0 0 6px;color:#d94f36;font-size:12px;font-weight:700;letter-spacing:.06em;">新闻事实 · {brief_origin}</p>'
        f'<p style="margin:0;color:#343936;font-size:16px;line-height:1.82;">{esc(news_brief)}</p>'
        '</div>'
    )
    trend_line = ""
    if story.get("discoverySource") == "百度热搜":
        rank = esc(story.get("hotRank") or "-")
        trend_line = f'<p style="margin:0 0 8px;color:#d94f36;font-size:12px;font-weight:700;">百度热搜第{rank}位发现 · 已回溯媒体原文</p>'
    observation = esc(story["whyItMatters"])
    observation = observation.replace(
        "判断：",
        '<strong style="color:#1d6a55;">判断：</strong>',
        1,
    ).replace(
        "验证重点：",
        '<br><strong style="color:#1d6a55;">验证重点：</strong>',
        1,
    )
    source_note = f"资料来源：{story['source']}"
    if story.get("discoverySource") == "百度热搜":
        source_note += "；百度热搜仅用于议题发现"
    source_note += "；详细资料与原文入口见文末“阅读原文”。"
    return f"""
    <section style="margin:0 0 20px;padding:0 0 18px;border-bottom:1px solid #e9e5dc;">
      <p style="margin:0 0 7px;line-height:1.5;"><span style="display:inline-block;margin-right:8px;padding:2px 7px;background:#d94f36;color:#fff;font-size:12px;font-weight:700;letter-spacing:.04em;">{section_number}-{number:02d}</span><span style="color:#8a5146;font-size:12px;font-weight:700;letter-spacing:.04em;">{esc(story['source'])} · {esc(story.get('publishedLabel', '今日'))}</span></p>
      {trend_line}
      <h3 style="margin:0 0 9px;color:#171a19;font-size:20px;line-height:1.45;font-weight:700;">{esc(story['title'])}</h3>
      {summary_line}
      {data_line}
      <p style="margin:0 0 10px;padding:10px 13px;background:#f5f3ee;border-left:3px solid #1d6a55;color:#4e5551;font-size:14px;line-height:1.7;"><strong style="color:#1d6a55;">小马观察</strong><br>{observation}</p>
      <p style="margin:0;color:#8a8f8b;font-size:12px;">{esc(source_note)}</p>
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
    <section style="margin:28px 0 14px;padding:14px 0 12px;border-top:3px solid #171a19;border-bottom:1px solid #e9e5dc;">
      <p style="margin:0 0 6px;"><span style="display:inline-block;padding:3px 9px;background:#171a19;color:#fff;font-size:12px;font-weight:700;letter-spacing:.08em;">栏目 {number}</span></p>
      <h2 style="margin:0 0 5px;color:#171a19;font-size:25px;line-height:1.3;font-weight:700;">{esc(title)}</h2>
      <p style="margin:0;color:#7a7f7b;font-size:13px;line-height:1.6;">{esc(subtitle)}</p>
    </section>"""


def select(stories: list[dict], categories: set[str], limit: int) -> list[tuple[int, dict]]:
    return [(i, s) for i, s in enumerate(stories) if s.get("category") in categories][:limit]


def focus_score(story: dict) -> int:
    text = f"{story.get('title', '')} {story.get('summary', '')} {story.get('newsBrief', '')}".lower()
    terms = {
        "新车": 8, "上市": 8, "首发": 7, "发布": 5, "车型": 6,
        "智能网联": 10, "车载ai": 10, "智能驾驶": 9, "自动驾驶": 9,
        "座舱": 8, "芯片": 7, "电池": 6, "充电": 5, "供应链": 7,
        "零部件": 6, "汽车金融": 8, "车贷": 8, "经销商": 6,
        "robotaxi": 9, "adas": 9, "connected-car": 9,
    }
    score = sum(weight for term, weight in terms.items() if term in text)
    data_terms = ("销量", "交付", "产量", "零售", "批发", "出口", "渗透率", "市场份额", "库存", "价格", "营收", "利润", "利润率", "毛利率", "净利润", "税前利润", "经营现金流", "自由现金流", "单车收入", "同比", "环比", "财报", "半年报", "季报", "ebit", "ebt", "sales", "deliveries", "revenue", "margin", "inventory", "free cash flow")
    score += min(36, sum(6 for term in data_terms if term in text))
    score += min(24, len(extract_metrics(story)) * 6)
    major_brands = ("特斯拉", "理想", "蔚来", "小鹏", "小米", "比亚迪", "tesla", "nio", "xpeng", "li auto", "xiaomi", "byd")
    major_events = ("上市", "首发", "发布", "交付", "销量", "财报", "利润", "召回", "降价", "涨价", "launch", "deliver", "earnings", "recall")
    if any(brand in text for brand in major_brands):
        score += 8
        if any(event in text for event in major_events):
            score += 24
    source = story.get("source", "")
    if source in {"工信部", "中国汽车工业协会", "中国汽车流通协会", "乘联会"} or any(
        term in text for term in ("工信部", "中汽协", "中国汽车工业协会", "中国汽车流通协会", "乘联分会", "乘联会")
    ):
        score += 24
    if any(term in text for term in ("新规", "国标", "监管", "召回", "安全要求", "消费税")):
        score += 16
    financial_hits = sum(term in text for term in ("财报", "半年报", "季报", "营收", "毛利率", "净利润", "经营现金流", "自由现金流", "ebit", "ebt", "financial results"))
    if financial_hits >= 2:
        score += 24
    if any(term in text for term in ("申报2026第八届金辑奖", "投融资周报", "概念异动", "直线涨停")):
        score -= 45
    brief = str(story.get("newsBrief", ""))
    if story.get("newsBriefSource") == "公开标题与已披露信息" or len(brief) < 90:
        score -= 24
    if any(term in text for term in ("自行车", "电动自行车")):
        score -= 50
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
    ranked = sorted(auto_items + finance_items, key=lambda item: focus_score(item[1]), reverse=True)
    bands = (
        ("今日重点", "政策、安全、行业拐点与最有决策价值的数据", ranked[:5]),
        ("行业追踪", "重要经营、技术量产与市场结构变化", ranked[5:10]),
        ("补充观察", "值得留意但影响范围或信息完整度相对有限的动态", ranked[10:]),
    )
    return [
        (f"{index:02d}", title, subtitle, items)
        for index, (title, subtitle, items) in enumerate(bands, 1)
        if items
    ]


def main() -> None:
    global ARCHIVE_DATE
    data = json.loads(DATA.read_text(encoding="utf-8"))
    ARCHIVE_DATE = date_key(data["dateLabel"])
    data["stories"] = sorted(data["stories"], key=focus_score, reverse=True)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stories = data["stories"]
    auto_industry = [(i, s) for i, s in enumerate(stories) if s.get("category") == "汽车产业"]
    auto_finance = [(i, s) for i, s in enumerate(stories) if s.get("category") == "汽车金融"]
    groups = topic_groups(auto_industry, auto_finance)
    selected = [item for _, _, _, items in groups for item in items]
    if len(auto_industry) < 9 or len(selected) < 9:
        raise ValueError("公众号汽车专刊缺少足够的汽车热点或汽车金融内容")
    lead_items = sorted(selected, key=lambda item: focus_score(item[1]), reverse=True)[:3]
    lead_title = lead_items[0][1]["title"]
    lead_heading = "今日重点速览"
    lead_body = f"本期收录{len(selected)}条汽车产业与汽车金融动态，覆盖" + "、".join(title for _, title, _, _ in groups) + "。以下按主题呈现新闻事实、关键数据与小马观察。"
    heading_titles = [lead_heading]
    heading_titles.extend(title for _, title, _, _ in groups)
    heading_titles.extend(story["title"] for _, _, _, items in groups for _, story in items)
    normalized_headings = [re.sub(r"\s+", " ", title).strip().casefold() for title in heading_titles]
    if len(normalized_headings) != len(set(normalized_headings)):
        raise ValueError("公众号正文存在重复标题")
    cover_result = render_cover(data)

    body: list[str] = []
    body.append(f"""
      <header style="padding:34px 24px;background:#171a19;color:#fff;">
        <p style="margin:0 0 12px;color:#ef7059;font-size:13px;font-weight:700;letter-spacing:.14em;">小马儿YOUNG · 汽车产业观察</p>
        <h1 style="margin:0 0 14px;font-size:30px;line-height:1.3;">{esc(data['dateLabel'])} 每日汽车透视</h1>
        <p style="margin:0;color:#c9ceca;font-size:15px;line-height:1.8;">聚焦智能网联、车载AI、整车与供应链、汽车金融，记录汽车产业每天值得关注的变化。</p>
      </header>
      <section style="margin:0;padding:26px 24px;background:#f5f3ee;border-bottom:1px solid #ddd8cc;">
        <p style="margin:0 0 8px;color:#d94f36;font-size:13px;font-weight:700;">今日汽车产业观察</p>
        <h2 style="margin:0 0 12px;color:#171a19;font-size:23px;line-height:1.45;">{esc(lead_heading)}</h2>
        <p style="margin:0;color:#454b47;font-size:15px;line-height:1.9;">{esc(lead_body)}</p>
      </section>""")

    for number, title, subtitle, items in groups:
        body.append(section_title(number, title, subtitle))
        body.extend(story_block(s, i, number, n) for n, (i, s) in enumerate(items, 1))
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
<title>{esc(data['dateLabel'])} · 小马儿Young每日汽车透视</title>
<style>body{{margin:0;background:#ecebe7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}}.toolbar{{position:sticky;top:0;z-index:5;padding:12px;text-align:center;background:#fff;border-bottom:1px solid #ddd}}button{{padding:10px 18px;border:0;border-radius:4px;background:#1d6a55;color:#fff;font-size:14px;cursor:pointer}}#wechat-article{{width:min(677px,100%);margin:24px auto;background:#fff;box-shadow:0 10px 35px rgba(0,0,0,.08)}}@media(max-width:700px){{#wechat-article{{margin:0 auto}}}}</style></head>
<body><div class="toolbar"><button id="copyButton">复制公众号正文</button> <span id="copyStatus"></span></div>
<main id="wechat-article">{article}</main>
<script>document.getElementById('copyButton').onclick=async()=>{{const article=document.getElementById('wechat-article');try{{await navigator.clipboard.write([new ClipboardItem({{'text/html':new Blob([article.innerHTML],{{type:'text/html'}}),'text/plain':new Blob([article.innerText],{{type:'text/plain'}})}})]);document.getElementById('copyStatus').textContent='已复制，可粘贴到公众号编辑器';}}catch(e){{const range=document.createRange();range.selectNode(article);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);document.execCommand('copy');document.getElementById('copyStatus').textContent='已复制';}}}};</script></body></html>"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document, encoding="utf-8")
    payload = {
        "title": f"{data['dateLabel']}｜每日汽车透视",
        "author": "小马儿Young",
        "digest": f"聚焦智能网联、车载AI、整车供应链与汽车金融。今日关注：{lead_title}"[:120],
        "content": article,
        "content_source_url": f"{SITE}/wechat.html?date={ARCHIVE_DATE}",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    PAYLOAD.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "payload": str(PAYLOAD), "cover": cover_result, "selected": len(selected), "sections": [title for _, title, _, _ in groups]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
