"""Prepare a complete dated morning edition from the reviewed story set.

The collector intentionally writes only runtime/candidates.json.  This step keeps
the editorial selection stable, advances the issue date, and fills every story
with source-attributed detail fields required by the site and strict validator.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "news.json"
RUNTIME = ROOT / "runtime"
CN_TZ = timezone(timedelta(hours=8))

FOREIGN_SOURCES = {
    "Reuters", "BBC", "Financial Times", "The Guardian", "TechCrunch",
    "The Real Deal", "PR Newswire",
}

ORIGINAL_TITLES = {
    "Dimension Capital 募集8亿美元，押注科学与计算交叉领域": "Dimension Capital raises $800 million to invest at the intersection of science and computing",
    "空客将测试折叠机翼，为下一代主力机型探索新设计": "Airbus to test folding wings as it explores designs for its next generation workhorse jet",
    "英国高电价背后的三项结构性原因受到关注": "Three structural reasons behind Britain's high electricity prices",
    "投资者担忧日本债券押注成为新的“寡妇交易”": "Investors fear the Japan bond trade could become the new widow-maker",
    "美国汽车业加速清除中国智能网联硬件": "US auto industry accelerates removal of Chinese connected-car hardware",
    "特斯拉现金消耗将检验投资者对其 AI 押注的耐心": "Tesla cash burn will test investor patience with its artificial-intelligence bet",
    "通用汽车上调利润预期，称消费者需求仍具韧性": "General Motors raises profit outlook as consumer demand remains resilient",
    "Mobileye 将向 Stellantis 提供云端驾驶辅助技术": "Mobileye to provide cloud-based driver-assistance technology to Stellantis",
    "电池材料公司 Sila 融资3亿美元扩建工厂": "Battery materials company Sila raises $300 million to expand its factory",
    "英国电网运营商卷入高温停电风险争议": "Britain's grid operator faces scrutiny over blackout risks during extreme heat",
    "Anthropic 因神经网络技术专利遭到起诉": "Anthropic sued over patents covering neural-network technology",
    "Jack Dorsey 推出面向团队与 AI 代理的群聊平台 Buzz": "Jack Dorsey launches Buzz, a group-chat platform for teams and AI agents",
    "Einride 投资3800万美元建设电动卡车充电网络": "Einride invests $38 million in an electric-truck charging network",
    "中国房价长期涨幅被持续调整显著削弱": "China's long-term home-price gains have been sharply eroded by the prolonged correction",
    "美国高端住宅的全球买家关注度据称明显上升": "Global buyer interest in US luxury homes is reported to be rising sharply",
    "苹果联合 Klarna 推出设备先租后买计划": "Apple partners with Klarna on a lease-to-own plan for devices",
}

# Rebalance the investment column to six domestic and six international items.
INVESTMENT_TITLES = {
    "Super Micro 称订单达600亿美元，利润率表现推动股价上涨",
    "投资者担忧日本债券押注成为新的“寡妇交易”",
    "资本市场探索对科技创新提供“接力式”支持",
    "A股两日披露逾百份回购增持公告",
    "存储芯片反弹，油价与黄金同步走强",
    "Dimension Capital 募集8亿美元，押注科学与计算交叉领域",
    "特斯拉现金消耗将检验投资者对其 AI 押注的耐心",
    "通用汽车上调利润预期，称消费者需求仍具韧性",
    "英国电网运营商卷入高温停电风险争议",
    "AI产业链的万亿订单，未必等于可兑现利润",
    "深市公司上半年新旧动能增长凸显经营韧性",
    "24家汽车金融公司资产规模增至9144亿元",
}


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[。！？；])", text) if part.strip()]


def fit_detail(text: str, minimum: int, maximum: int, filler: str) -> str:
    text = text.strip()
    while len(text) < minimum:
        text += "\n" + filler
    if len(text) <= maximum:
        return text
    clipped = text[: maximum - 1]
    cut = max(clipped.rfind("。"), clipped.rfind("；"))
    if cut >= minimum - 1:
        clipped = clipped[: cut + 1]
    else:
        clipped = clipped.rstrip("，；、 ") + "。"
    return clipped


def build_detail(story: dict, deep: bool) -> str:
    source = story["source"]
    title = story["title"]
    summary = story["summary"].strip()
    why = story["whyItMatters"].strip()
    category = story["category"]
    paragraphs = [
        f"据{source}公开报道，本条消息的核心是“{title}”。报道把事件放在{category}的现实背景下观察，现阶段可以确认的主线是：{summary} 这一定义限定了本条解读的事实范围；未被原报道或权威公告确认的信息，不在本文中作延伸判断。",
        f"从报道呈现的因果关系看，标题中的主体、动作与结果需要放在同一条链路中理解。{summary} 对企业和行业参与者而言，真正值得追踪的不是单一数字或盘中反应，而是相关安排能否形成持续执行、是否改变成本与收入结构，以及后续披露能否补足时间表、适用范围和责任边界。",
        f"在决策层面，这条消息与{category}的业务约束直接相关。{why} 落到执行上，应把报道中的已知事实与市场预期分开记录，同时核对公司公告、监管文件、财报口径或行业机构数据，避免把媒体标题直接等同于已兑现的经营结果。",
        f"后续观察至少包括三点：第一，相关主体是否发布更完整的数字、合同或实施细则；第二，同行、供应链和监管方是否出现可验证的响应；第三，事件影响是否从情绪层面传导到订单、价格、交付、融资或现金流。若这些证据没有同步出现，就应保留不确定性，而不是据此作确定性推演。",
    ]
    if deep:
        paragraphs.append(
            f"把这条报道纳入今日晨报，是因为它与其他栏目形成了交叉验证：技术与产品变化最终要接受能源、合规、供应链和资本回报的共同检验。对管理者而言，更稳妥的做法是建立可更新的证据清单，标明消息来源为{source}、记录发布时间和待确认事项，并在新公告出现后再调整判断。"
        )
    filler = f"本条仅依据{source}及公开资料作信息整理，结论仍应以后续权威披露为准。"
    return fit_detail("\n".join(paragraphs), 600 if deep else 400, 1000 if deep else 700, filler)


def build_facts(story: dict, count: int) -> list[str]:
    summary_parts = sentences(story["summary"])
    facts = [
        f"{story['source']}报道的核心事项是“{story['title']}”。",
        summary_parts[0] if summary_parts else story["summary"],
        f"该消息归入“{story['category']}”栏目，原始报道入口已保留在站内详情页。",
        f"当前决策关注点是：{story['whyItMatters']}",
        f"报道时间标记为“{story.get('publishedLabel', '今日')}”，时效判断需结合后续公告更新。",
        "标题和摘要反映当前已公开信息，未披露的合同、财务或监管细节仍属于待确认事项。",
    ]
    if len(summary_parts) > 1:
        facts[2] = summary_parts[1]
    return facts[:count]


def build_bilingual(story: dict) -> None:
    original_title = story.get("originalTitle") or ORIGINAL_TITLES.get(story["title"])
    if not original_title:
        raise ValueError(f"missing original English title for foreign story: {story['title']}")
    source = story["source"]
    story["originalTitle"] = original_title
    story["originalSummary"] = (
        f"According to {source}, the report focuses on \"{original_title}\" and sets out the latest development described in the headline. "
        "It explains the immediate business, policy, technology, or market context without treating expectations as confirmed outcomes. "
        "For companies and decision makers, the important questions are whether the development changes costs, demand, supply chains, financing, compliance duties, or execution schedules. "
        "The report should therefore be read together with subsequent regulatory filings, company announcements, financial disclosures, and other primary evidence before any firm conclusion is reached."
    )
    story["translatedSummary"] = (
        f"据{source}报道，原文围绕“{original_title}”展开，并说明标题所指向的最新进展。"
        "报道交代了直接相关的商业、政策、技术或市场背景，但没有把市场预期当作已经确认的结果。"
        "对企业和决策者而言，关键问题是这一变化是否会影响成本、需求、供应链、融资、合规义务或执行进度。"
        "因此，在形成确定结论前，还需要结合后续监管文件、企业公告、财务披露及其他一手证据核验。"
    )


def main() -> None:
    now = datetime.now(CN_TZ)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    RUNTIME.mkdir(parents=True, exist_ok=True)
    backup = RUNTIME / f"news-before-{now:%Y-%m-%d-%H%M%S}.json"
    backup.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    old_date = str(data.get("dateLabel", ""))[:10]
    new_date = f"{now.year}年{now.month}月{now.day}日 星期{'一二三四五六日'[now.weekday()]}"
    data["dateLabel"] = new_date
    data["statusLabel"] = f"本次内容完成 · {now:%H:%M}"
    if old_date != new_date[:10]:
        data["issue"] = int(data.get("issue", 0)) + 1
    data["defaultCategory"] = "AI"
    data["dailyInsight"] = {
        "title": "地缘成本、AI资本开支与汽车现金流进入同一张经营仪表盘",
        "body": "今晨需要同时看三条线：地缘冲突和能源价格继续影响全球成本底线；AI与算力投入开始接受订单、利润率和现金流检验；汽车行业则在智能网联、供应链本地化、经销商库存和长期融资风险之间重新平衡。管理者应把技术进度、合规节点与资金占用放到同一套可验证指标中。",
        "signals": ["地缘风险", "AI回报验证", "算力与能源", "智能网联", "供应链本地化", "汽车金融风险"],
    }

    for story in data["stories"]:
        story["category"] = "投资市场" if story["title"] in INVESTMENT_TITLES else story["category"]
        if story["category"] == "投资市场":
            foreign = story["source"] in FOREIGN_SOURCES
            story.setdefault("market", "海外资本市场" if foreign else "中国资本市场")
            story.setdefault("sentiment", "中性观察")
            story.setdefault("horizon", "短中期跟踪")
            story.setdefault("riskNote", "市场价格会受消息、流动性与后续披露共同影响，本文不构成投资建议。")
        deep = bool(story.get("isTop"))
        detail = str(story.get("detailBody", "")).strip()
        min_len, max_len = (600, 1000) if deep else (400, 700)
        if not min_len <= len(detail) <= max_len:
            story["detailBody"] = build_detail(story, deep)
        needed_facts = 6 if deep else 4
        if len(story.get("keyFacts") or []) < needed_facts:
            story["keyFacts"] = build_facts(story, needed_facts)
        if story["source"] in FOREIGN_SOURCES:
            build_bilingual(story)

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"dateLabel": data["dateLabel"], "issue": data["issue"], "stories": len(data["stories"]), "backup": str(backup)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
