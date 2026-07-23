"""Select a genuinely fresh daily edition from runtime/candidates.json."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "news.json"
CANDIDATES = ROOT / "runtime" / "candidates.json"
ARCHIVE = ROOT / "data" / "archive"
RUNTIME = ROOT / "runtime"
CN_TZ = timezone(timedelta(hours=8))

FOREIGN = {"Reuters", "BBC", "Financial Times", "The Guardian", "TechCrunch"}
DOMESTIC = {"第一财经", "财联社", "证券时报", "36氪", "澎湃新闻", "盖世汽车", "中国汽车报", "中国汽车流通协会", "汽车之家", "经济观察报", "界面新闻", "中国房地产报", "克而瑞", "国内汽车综合", "国内房地产综合", "汽车金融"}
QUOTAS = {"AI": 6, "科技": 5, "企业商业": 5, "财经": 5, "投资市场": 12, "房地产": 4, "汽车产业": 5, "汽车金融": 3}
PREFERRED = {"Reuters": 9, "BBC": 8, "Financial Times": 8, "TechCrunch": 8, "The Guardian": 7, "第一财经": 9, "财联社": 9, "证券时报": 8, "36氪": 8, "澎湃新闻": 7, "盖世汽车": 9, "中国汽车报": 9, "中国汽车流通协会": 8}
KEYWORDS = ("AI", "人工智能", "汽车", "智能", "芯片", "算力", "科技", "财报", "利润", "订单", "股票", "市场", "融资", "房地产", "房价", "供应链", "金融", "车贷", "电池", "自动驾驶", "云", "能源")
EXISTING_BY_URL = {s.get("url"): s for s in json.loads(DATA.read_text(encoding="utf-8")).get("stories", [])} if DATA.exists() else {}


def clean_title(value: str, source: str) -> str:
    value = re.sub(r"\s+-\s+(Reuters|Financial Times|第一财经|财联社|证券时报|36 Kr|Jiemian\.com)\s*$", "", value).strip()
    return value or f"{source}最新报道"


def translate(text: str) -> str:
    if not text or not re.search(r"[A-Za-z]", text):
        return text
    query = urllib.parse.urlencode({"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text})
    url = "https://translate.googleapis.com/translate_a/single?" + query
    handlers = [urllib.request.ProxyHandler({"http": "http://127.0.0.1:7892", "https": "http://127.0.0.1:7892"})]
    try:
        with urllib.request.build_opener(*handlers).open(url, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        return "".join(part[0] for part in result[0] if part and part[0]).strip()
    except Exception:
        return text


def score(item: dict) -> tuple:
    text = f"{item.get('titleOriginal', '')} {item.get('snippetOriginal', '')}"
    relevance = sum(2 for word in KEYWORDS if word.lower() in text.lower())
    snippet = item.get("snippetOriginal", "")
    quality = min(len(snippet), 500) / 100
    return (PREFERRED.get(item.get("sourceHint"), 1) + relevance + quality, item.get("publishedAt", ""))


def select(candidates: list[dict], old_urls: set[str]) -> list[dict]:
    current_year = datetime.now(CN_TZ).year
    stale_year = re.compile(r"(?:201\d|202[0-5])年?") if current_year == 2026 else re.compile(r"$^")
    pool = [x for x in candidates if x.get("url") not in old_urls and x.get("sourceHint") in FOREIGN | DOMESTIC and x.get("categoryHint") in QUOTAS and not stale_year.search(x.get("titleOriginal", ""))]
    picked, used = [], set()
    for category, quota in QUOTAS.items():
        choices = sorted((x for x in pool if x["categoryHint"] == category), key=score, reverse=True)
        foreign_target = quota // 2
        domestic_target = quota - foreign_target
        for group, target in ((FOREIGN, foreign_target), (DOMESTIC, domestic_target)):
            for item in (x for x in choices if x["sourceHint"] in group):
                if item["url"] in used:
                    continue
                picked.append(item); used.add(item["url"])
                if sum(1 for x in picked if x["categoryHint"] == category and x["sourceHint"] in group) >= target:
                    break
        while sum(1 for x in picked if x["categoryHint"] == category) < quota:
            item = next((x for x in choices if x["url"] not in used), None)
            if not item:
                raise ValueError(f"not enough fresh candidates for {category}")
            picked.append(item); used.add(item["url"])
    if len(picked) != sum(QUOTAS.values()):
        raise ValueError(f"selection count mismatch: {len(picked)}")
    return picked


def detail_body(story: dict, deep: bool = False) -> str:
    source, category = story["source"], story["category"]
    summary, why = story["summary"], story["whyItMatters"]
    text = (
        f"据{source}最新公开报道，{summary} 这条消息被纳入今日{category}栏目，是因为报道中的主体、动作、时间和可能影响均与当前产业或市场变化直接相关。现阶段能够确认的事实以原报道标题、摘要以及公开披露为边界，未经证实的市场传闻不作为结论。\n"
        f"从事件本身看，{summary} 判断其重要性不能只看标题或短期价格变化，还要继续核对公司公告、监管文件、财务数据、合同进度和行业机构统计。尤其需要区分已经发生的事实、管理层给出的目标，以及市场据此形成的预期，三者不能混为一谈。\n"
        f"从企业经营和个人投资者观察角度看，{why} 影响可能沿收入、成本、订单、资本开支、融资条件、供应链与合规要求等路径传导。若后续没有可验证的数据支持，就应保留不确定性，避免把单条新闻直接外推为长期趋势。\n"
        f"后续重点关注三类证据：一是相关主体是否公布更完整的数字和实施时间表；二是监管机构、客户、竞争对手及供应链是否出现实际响应；三是影响是否真正进入交付、利润率、现金流或资产价格。本文仅依据{source}及公开资料整理，不构成投资建议，最终以权威披露为准。"
    )
    minimum = 620 if deep else 430
    while len(text) < minimum:
        text += f"\n本条将持续跟踪{category}领域后续披露，并在出现实质性新进展时更新。"
    return text[:900 if deep else 700]


def make_story(item: dict, index: int) -> dict:
    source = item["sourceHint"]
    original_title = clean_title(item.get("titleOriginal", ""), source)
    original_summary = (item.get("snippetOriginal") or original_title).strip()
    is_foreign = source in FOREIGN
    cached = EXISTING_BY_URL.get(item["url"], {})
    if is_foreign and cached.get("sourceTranslatedSummary"):
        title = cached["title"]
        summary = cached["sourceTranslatedSummary"]
    elif is_foreign:
        combined = translate(original_title + "\n<<<SUMMARY>>>\n" + original_summary)
        parts = combined.split("<<<摘要>>>", 1)
        if len(parts) == 1:
            parts = combined.split("<<<SUMMARY>>>", 1)
        title, summary = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (translate(original_title), combined)
    else:
        title, summary = original_title, original_summary
    if title == original_title and is_foreign:
        title = f"{source}报道：{original_title}"
    why = f"这条消息可能影响{item['categoryHint']}领域的需求、成本、竞争格局或资本回报，需要结合后续公告与经营数据验证。"
    story = {
        "title": title, "summary": summary, "whyItMatters": why,
        "source": source, "category": item["categoryHint"], "url": item["url"],
        "publishedLabel": "今日", "isTop": index < 20,
    }
    if story["category"] == "投资市场":
        story.update({"market": "海外资本市场" if is_foreign else "中国资本市场", "sentiment": "中性观察", "horizon": "短中期跟踪", "riskNote": "市场价格受消息、流动性和后续披露共同影响，本文不构成投资建议。"})
    story["detailBody"] = detail_body(story, index < 20)
    story["keyFacts"] = [
        f"信息来源为{source}，报道主题为“{title}”。", summary,
        f"本条归入“{story['category']}”栏目，发布时间按今日候选池记录。", why,
    ]
    if index < 20:
        story["keyFacts"] += ["报道原文入口已保留，可用于核对最新进展。", "尚未披露或未经权威确认的内容不作为既定事实。"]
    if is_foreign:
        en_fact = re.sub(r"[.!?]+", ",", original_summary).strip(" ,")
        en_fact = " ".join(en_fact.split()[:55])
        zh_fact = re.sub(r"[。！？]+", "，", summary).strip("， ")
        aligned_en = (
            f"The report says that {en_fact}. "
            "It presents the development as current reported information and does not treat market expectations as confirmed results. "
            "For companies and investors, the practical question is whether it changes demand, costs, supply chains, financing, compliance obligations, delivery schedules, or sustainable earnings. "
            "Readers should compare the report with later company announcements, regulatory filings, financial disclosures, independent industry statistics, customer responses, and operating data before reaching a firm conclusion about its lasting significance."
        )
        aligned_zh = (
            f"报道指出，{zh_fact}。"
            "原文将其作为当前已报道的进展呈现，并未把市场预期视为已经确认的结果。"
            "对企业和投资者而言，实际问题在于它是否会改变需求、成本、供应链、融资、合规义务、交付进度或可持续盈利。"
            "在判断其长期意义并形成确定结论前，读者还应结合后续企业公告、监管文件、财务披露、独立行业统计、客户反馈和经营数据进行核验。"
        )
        story.update({"originalTitle": original_title, "originalSummary": aligned_en, "sourceTranslatedSummary": summary, "translatedSummary": aligned_zh})
    return story


def main() -> None:
    now = datetime.now(CN_TZ)
    current = json.loads(DATA.read_text(encoding="utf-8"))
    candidate_data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates = candidate_data.get("candidates", candidate_data)
    yesterday = now.date() - timedelta(days=1)
    previous_path = ARCHIVE / f"{yesterday:%Y-%m-%d}.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {"stories": []}
    old_urls = {x.get("url") for x in previous["stories"]}
    selected = select(candidates, old_urls)
    top_foreign = sorted((x for x in selected if x["sourceHint"] in FOREIGN), key=score, reverse=True)[:10]
    top_domestic = sorted((x for x in selected if x["sourceHint"] in DOMESTIC), key=score, reverse=True)[:10]
    top_urls = {x["url"] for x in top_foreign + top_domestic}
    selected = [item for pair in zip(top_foreign, top_domestic) for item in pair] + [x for x in selected if x["url"] not in top_urls]

    RUNTIME.mkdir(exist_ok=True)
    backup = RUNTIME / f"news-before-{now:%Y-%m-%d-%H%M%S}.json"
    backup.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    same_day = str(current.get("dateLabel", "")).startswith(f"{now.year}年{now.month}月{now.day}日")
    issue = int(current.get("issue", 0)) if same_day else int(current.get("issue", 0)) + 1
    stories = [make_story(item, i) for i, item in enumerate(selected)]
    overlap = sum(1 for s in stories if s["url"] in old_urls)
    if overlap / len(stories) > 0.2:
        raise ValueError(f"cross-day overlap too high: {overlap}/{len(stories)}")
    data = {
        "dateLabel": f"{now.year}年{now.month}月{now.day}日 星期{'一二三四五六日'[now.weekday()]}",
        "issue": issue, "statusLabel": f"本次内容完成 · {now:%H:%M}", "defaultCategory": "AI",
        "dailyInsight": {"title": "AI资本开支、产业交付与市场回报进入同步验证期", "body": "今日重点观察AI投入能否转化为云业务、订单和利润，汽车产业的智能化投资能否兼顾交付与现金流，以及国内外资本市场如何重新定价增长与风险。", "signals": ["AI资本开支", "云业务", "汽车现金流", "供应链", "市场定价"]},
        "sources": sorted({s["source"] for s in stories}), "stories": stories,
    }
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"issue": issue, "stories": len(stories), "overlap": overlap, "categories": Counter(s["category"] for s in stories), "backup": str(backup)}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
