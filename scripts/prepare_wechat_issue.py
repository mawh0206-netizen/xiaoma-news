"""Build an automotive-only WeChat edition independently of the website brief."""
from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import prepare_daily_issue as daily
from google_news_url import is_google_news_url, resolve_urls

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "runtime" / "candidates.json"
OUTPUT = ROOT / "runtime" / "wechat_news.json"
METRIC_RE = re.compile(
    r"(?:约|超|近|达|增长|下降)?\s*\d+(?:\.\d+)?\s*"
    r"(?:%|万亿元|亿元|万美元|亿美元|万元|万辆|万台|万套|万|美元|元|辆|台|家|倍)",
    re.I,
)


def fresh(item: dict, now: datetime) -> bool:
    title = item.get("titleOriginal", "")
    if re.search(r"(?:201\d|202[0-5])年?", title):
        return False
    months = {int(value) for value in re.findall(r"(?<!\d)(1[0-2]|[1-9])月", title)}
    allowed = {now.month, 12 if now.month == 1 else now.month - 1}
    return not months or bool(months & allowed)


def choose(pool: list[dict], limit: int, topic_coverage: bool) -> list[dict]:
    ranked = sorted(pool, key=daily.score, reverse=True)
    ordered: list[dict] = []
    if topic_coverage:
        for topic in ("data", "smart", "vehicle", "supply", "industry"):
            candidate = next((item for item in ranked if daily.auto_subtopic(item) == topic and item not in ordered), None)
            if candidate:
                ordered.append(candidate)
    ordered.extend(item for item in ranked if item not in ordered)
    selected: list[dict] = []
    for item in ordered:
        if daily.too_similar(item, selected):
            continue
        if sum(existing["sourceHint"] == item["sourceHint"] for existing in selected) >= 2:
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    if len(selected) < limit:
        raise ValueError(f"not enough independent WeChat automotive candidates: {len(selected)}/{limit}")
    return selected


def metrics_from(story: dict) -> list[str]:
    text = f"{story.get('title', '')} {story.get('summary', '')}"
    values: list[str] = []
    for value in METRIC_RE.findall(text):
        cleaned = re.sub(r"\s+", "", value)
        if cleaned not in values:
            values.append(cleaned)
    return values[:3]


def short_subject(story: dict) -> str:
    title = re.sub(r"_文章.*$", "", story.get("title", "")).strip()
    title = re.sub(r"\s+[-—]\s+[^-—]{2,16}$", "", title).strip()
    return title if len(title) <= 26 else title[:25] + "…"


def professional_observation(story: dict) -> tuple[str, list[str]]:
    text = f"{story.get('title', '')} {story.get('summary', '')}".lower()
    subject = short_subject(story)
    metrics = metrics_from(story)
    data_anchor = f"报道中的{'、'.join(metrics)}需要放回统计口径和时间周期中看，" if metrics else ""

    if story.get("category") == "汽车金融":
        if any(term in text for term in ("0首付", "零首付", "低首付")):
            if any(term in text for term in ("新规", "实探", "成色", "监管")):
                judgment = (
                    f"“{subject}”要验证的是新规落地后产品有没有把首付门槛变成隐性融资成本。"
                    f"{data_anchor}低首付本身并不违规，但销售流程必须充分披露实际年化利率、"
                    "附加服务和提前还款条件，否则成交提升会以投诉、退贷和合规成本的形式回流。"
                )
                watch = ["合同实际年化利率", "捆绑服务费用", "提前还款率", "投诉与退贷率"]
            else:
                judgment = (
                    f"“{subject}”的核心不是促销力度，而是信用风险从首付款转移到更高贷款价值比。"
                    f"{data_anchor}短期订单转化可能改善，但如果利率补贴、残值假设和经销商回购责任不透明，"
                    "坏账与提前结清成本会在后端暴露。"
                )
                watch = ["实际年化利率", "贷款价值比LTV", "首期逾期率", "经销商追索责任"]
        elif any(term in text for term in ("银行", "汽车金融公司", "车贷", "金融市场")):
            judgment = (
                f"“{subject}”意味着获客竞争正从审批速度转向资金成本与风险定价。"
                f"{data_anchor}产品侧不能只比较名义利率，还要拆分贴息来源、审批通过率、"
                "提前还款规则以及银行和汽车金融公司的客群分层。"
            )
            watch = ["审批通过率", "资金成本", "单车贴息", "30天以上逾期率"]
        else:
            judgment = (
                f"“{subject}”不能简单解读为金融渗透率越高越好。{data_anchor}"
                "真正决定业务质量的是金融是否带来新增成交，同时没有用过度授信掩盖终端需求不足。"
            )
            watch = ["金融渗透率", "单车融资额", "新增成交贡献", "不良率"]
    elif any(term in text for term in ("销量目标", "销售目标", "交付目标", "产量目标")):
        judgment = (
            f"“{subject}”中各企业目标的简单加总并不等于真实市场容量。{data_anchor}"
            "目标要成立，必须同时满足终端需求、渠道库存和产能利用率三项约束；"
            "如果零售增速跟不上批发目标，压力最终会转化为价格折让和经销商资金占用。"
        )
        watch = ["终端零售", "批零差", "渠道库存天数", "产能利用率"]
    elif any(term in text for term in ("产量", "生产")) and any(term in text for term in ("下降", "暴跌", "下滑", "推迟")):
        judgment = (
            f"“{subject}”更像供需失衡或生产切换信号，不能用常规销量增长逻辑解释。{data_anchor}"
            "需要先区分减产来自订单不足、零部件约束还是车型换代；若同时推迟新品，"
            "说明问题可能已从单月波动扩展到研发、认证或供应协同。"
        )
        watch = ["工厂产能利用率", "在手订单", "零部件缺口", "新品认证与投产节点"]
    elif any(term in text for term in ("销量", "交付", "产量", "零售", "出口", "市场份额")):
        judgment = (
            f"“{subject}”提供了规模信号，但单一销量数字不足以判断经营质量。{data_anchor}"
            "需要区分批发、零售、出口和库存转移，并观察增长是否依赖降价；"
            "只有份额提升与单车盈利同步，规模增长才具有可持续性。"
        )
        watch = ["批发与零售差值", "出口占比", "成交均价", "单车毛利"]
    elif any(term in text for term in ("渗透率", "新能源市场", "市场展望")):
        judgment = (
            f"“{subject}”反映的是结构变化，不是所有品牌都能同比例受益。{data_anchor}"
            "渗透率上升后，竞争重点会从教育市场转向价格带覆盖、补能体验和存量用户复购，"
            "弱产品组合反而更容易在高渗透阶段被淘汰。"
        )
        watch = ["分价格带渗透率", "区域差异", "复购率", "新能源单车利润"]
    elif any(term in text for term in ("智能驾驶", "自动驾驶", "线控", "座舱", "车载ai", "adas", "robotaxi")):
        if any(term in text for term in ("线控", "底盘")):
            judgment = (
                f"“{subject}”涉及的是自动驾驶执行层，价值不在概念先进，而在冗余、安全和整车集成。"
                f"{data_anchor}线控底盘要进入量产，必须通过功能安全验证并与制动、转向和域控制器协同，"
                "单一零部件参数领先并不能替代主机厂的系统级验证。"
            )
            watch = ["功能安全等级", "冗余方案", "主机厂定点", "量产故障率"]
        elif any(term in text for term in ("奖", "申报")):
            judgment = (
                f"“{subject}”目前提供的是技术案例背书，而不是新增订单证明。"
                f"{data_anchor}奖项材料应继续核对对应车型、实际装车规模和客户验收结果；"
                "只有案例能复制到更多平台并保持交付质量，技术影响力才会转化为商业壁垒。"
            )
            watch = ["对应量产车型", "累计装车量", "客户验收", "跨平台复用率"]
        elif any(term in text for term in ("研讨会", "发布会")):
            judgment = (
                f"“{subject}”说明产业协同议题升温，但会议和发布活动本身不会形成收入。"
                f"{data_anchor}后续应看技术方案是否形成主机厂联合开发、测试标准或正式定点，"
                "尤其要关注从样件到量产件的验证周期和成本变化。"
            )
            watch = ["联合开发项目", "测试标准", "量产定点", "样件转量产周期"]
        else:
            judgment = (
                f"“{subject}”的判断重点应从功能清单转向可规模化交付。{data_anchor}"
                "智能驾驶或车载AI只有在量产车型覆盖、用户使用频次、安全表现和单车成本之间形成闭环，"
                "才会从营销卖点变成持续收入或品牌溢价。"
            )
        watch = ["量产定点与SOP", "装车量", "用户使用率", "单车硬件与算力成本"]
    elif any(term in text for term in ("供应链", "电池", "芯片", "零部件", "工厂", "产能", "关税", "硬件")):
        judgment = (
            f"“{subject}”首先影响的不是传播声量，而是BOM成本、供应连续性和合规路径。"
            f"{data_anchor}企业需要判断变化是一次性扰动还是会迫使供应商本地化，"
            "并评估替代件验证周期是否会拖慢车型交付。"
        )
        watch = ["BOM成本变化", "替代供应商验证周期", "客户集中度", "交付周期"]
    elif any(term in text for term in ("召回", "安全", "故障")):
        judgment = (
            f"“{subject}”应按产品质量事件处理，而不是普通舆情。{data_anchor}"
            "影响大小取决于涉及车辆范围、修复方式、单车成本和问题是否触及核心安全功能；"
            "处理速度会直接影响用户信任与后续车型转化。"
        )
        watch = ["涉及车辆数", "单车修复成本", "到店完成率", "后续投诉率"]
    elif any(term in text for term in ("新车", "首发", "上市", "车型", "suv", "轿车")):
        if any(term in text for term in ("转型", "东风日产", "合资")):
            judgment = (
                f"“{subject}”承担的不只是单车销量任务，也是传统品牌新能源转型的渠道验证。"
                f"{data_anchor}关键要看燃油车经销网络能否有效承接新能源获客与服务，"
                "以及新车定价是否会冲击原有产品体系而没有带来新增用户。"
            )
            watch = ["新能源线索转化", "经销商单店销量", "增购用户占比", "油电产品价格重叠"]
        elif any(term in text for term in ("亚洲", "欧洲", "全球", "海外")):
            judgment = (
                f"“{subject}”检验的是同一电动车平台跨区域复制的效率。{data_anchor}"
                "海外扩张不能只看上市国家数量，还要比较本地认证、电池供应、渠道成本和定价后的竞争力；"
                "区域版本差异过大，会削弱平台规模效应。"
            )
            watch = ["区域售价", "本地认证进度", "电池本地化率", "单平台全球销量"]
        elif any(term in text for term in ("智慧", "智能", "r-tech")):
            judgment = (
                f"“{subject}”把智能化作为核心卖点，真正的产品差异要落到用户可感知体验。"
                f"{data_anchor}应重点验证功能是否随车交付、OTA节奏是否稳定，"
                "以及智能配置带来的成本能否通过选装率或成交溢价收回。"
            )
            watch = ["功能随车交付率", "OTA频次", "智能配置选装率", "成交溢价"]
        else:
            judgment = (
                f"“{subject}”完成的是产品亮相，不是市场验证。{data_anchor}"
                "产品经理更应关注它是否填补明确价格带和使用场景，"
                "以及订单转化、交付爬坡和同品牌内部替代是否支持预期规模。"
            )
            watch = ["权益后成交价", "订单转化率", "交付爬坡", "同品牌车型蚕食率"]
    else:
        judgment = (
            f"“{subject}”值得关注的不是事件本身，而是它是否改变产品供给、用户选择或企业经营约束。"
            f"{data_anchor}判断价值应落到可跟踪的业务指标，而不是用一次发布或单一口径外推长期趋势。"
        )
        watch = ["后续正式公告", "终端用户反馈", "商业化进度", "经营数据兑现"]

    observation = f"判断：{judgment} 验证重点：{'、'.join(watch)}。"
    return observation, watch


def main() -> None:
    now = datetime.now(daily.CN_TZ)
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", payload)
    valid_sources = daily.FOREIGN | daily.DOMESTIC | {"重点车企"}
    pool = [
        item for item in candidates
        if item.get("sourceHint") in valid_sources
        and item.get("categoryHint") in {"汽车产业", "汽车金融"}
        and daily.automotive_relevant(item)
        and fresh(item, now)
    ]
    auto_pool = [item for item in pool if item["categoryHint"] == "汽车产业"]
    finance_pool = [item for item in pool if item["categoryHint"] == "汽车金融"]
    domestic_auto = choose([item for item in auto_pool if item["sourceHint"] not in daily.FOREIGN], 7, True)
    foreign_auto = choose([item for item in auto_pool if item["sourceHint"] in daily.FOREIGN], 3, True)
    finance = choose([item for item in finance_pool if item["sourceHint"] not in daily.FOREIGN], 4, False)
    auto = domestic_auto + foreign_auto
    selected = auto + finance
    domestic_count = sum(item["sourceHint"] not in daily.FOREIGN for item in selected)
    domestic_ratio = domestic_count / len(selected)
    if not 0.75 <= domestic_ratio <= 0.85:
        raise ValueError(f"WeChat domestic source ratio outside target range: {domestic_count}/{len(selected)}")
    stories = [daily.make_story(item, index + 30) for index, item in enumerate(selected)]
    resolved_urls = resolve_urls([item["url"] for item in selected])
    for story, item in zip(stories, selected):
        original_url = item["url"]
        direct_url = resolved_urls.get(original_url, original_url)
        if is_google_news_url(direct_url):
            raise ValueError(f"WeChat publisher URL unresolved: {story['source']} / {story['title']}")
        if direct_url != original_url:
            story["aggregatorUrl"] = original_url
        story["url"] = direct_url
        observation, watch = professional_observation(story)
        story["whyItMatters"] = observation
        story["watchMetrics"] = watch
    observations = [story["whyItMatters"] for story in stories]
    if len(set(observations)) != len(observations):
        raise ValueError("WeChat professional observations must be unique")
    if any(len(observation) < 80 or "这条消息可能影响" in observation for observation in observations):
        raise ValueError("WeChat professional observation quality check failed")
    for left in range(len(observations)):
        for right in range(left + 1, len(observations)):
            similarity = SequenceMatcher(None, observations[left], observations[right]).ratio()
            if similarity > 0.78:
                raise ValueError(f"WeChat professional observations too similar: {left + 1}/{right + 1} ({similarity:.2f})")
    data = {
        "dateLabel": f"{now.year}年{now.month}月{now.day}日 星期{'一二三四五六日'[now.weekday()]}",
        "statusLabel": f"公众号选题完成 · {now:%H:%M}",
        "sources": sorted({story["source"] for story in stories}),
        "stories": stories,
    }
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "auto": len(auto), "finance": len(finance), "stories": len(stories), "domestic": domestic_count, "foreign": len(selected) - domestic_count, "domesticRatio": round(domestic_ratio, 3)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
