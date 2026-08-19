"""Build an automotive-only WeChat edition independently of the website brief."""
from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser
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
OBSERVATION_FINAL_LIMIT = 0.78
# Selection needs a buffer because the final story can reuse a richer cached
# summary than the candidate preview. Without a buffer, a pair just below the
# preview threshold can cross the hard final threshold and abort the edition.
OBSERVATION_SELECTION_LIMIT = 0.74
ARTICLE_UA = "Mozilla/5.0 (compatible; XiaomaNews/1.0; +https://mawh0206-netizen.github.io/xiaoma-news/)"
LOW_INFORMATION_TERMS = (
    "申报2026第八届金辑奖", "申报金辑奖", "投融资周报", "概念异动",
    "直线涨停", "时事通讯：", "newsletter:", "目前暂无", "座舱开箱",
    "回归\"长期主义\"", "回归“长期主义”", "+faq", "news - electric vehicle",
    "一锤定音", "豹启新境", "开始抄", "supposedly", "coffee to cars",
    "带火的这个设计", "东风股份：7月汽车销量", "美国混动市场 86%",
    "电池税”落地", "广汽孵化的机器人公司",
    "技术平权", "磨三剑", "掀开了速成车", "ai\"评测\"", "ai“评测”",
)
WEAK_AUTO_TERMS = ("自行车", "电动自行车", "两轮车")
BOILERPLATE_CONTACT_TERMS = (
    "联系邮箱", "求职应聘", "简历投递", "客服微信", "新闻热线",
    "商务合作", "市场合作", "项目咨询", "zhaopin@", "info@gasgoo",
)


class ArticleMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.descriptions: list[str] = []
        self.paragraphs: list[str] = []
        self._paragraph_parts: list[str] | None = None
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if tag == "p" and not self._ignored_depth:
            self._paragraph_parts = []
        if tag != "meta":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        name = (values.get("name") or values.get("property") or "").lower()
        if name in {"description", "og:description", "twitter:description"} and values.get("content"):
            self.descriptions.append(values["content"])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag == "p" and self._paragraph_parts is not None:
            paragraph = clean_news_text(" ".join(self._paragraph_parts))
            if paragraph:
                self.paragraphs.append(paragraph)
            self._paragraph_parts = None

    def handle_data(self, data: str) -> None:
        if self._paragraph_parts is not None and not self._ignored_depth:
            self._paragraph_parts.append(data)


def clean_news_text(value: object) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<<<(?:SUMMARY|总结|摘要)>>>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"#[^#]{2,50}#", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?:继续阅读|阅读全文|点击查看详情)\s*[.…]*$", "", text).strip()
    return text


def decode_article_html(raw: bytes, header_charset: str | None = None) -> str:
    """Decode publisher HTML using HTTP metadata plus the document's own charset."""
    prefix = raw[:8192].decode("ascii", errors="ignore")
    meta_match = re.search(
        r"<meta[^>]+charset\s*=\s*[\"']?\s*([a-zA-Z0-9._-]+)",
        prefix,
        flags=re.I,
    )
    charsets = [meta_match.group(1) if meta_match else "", header_charset or "", "utf-8", "gb18030"]
    for charset in dict.fromkeys(value.strip() for value in charsets if value and value.strip()):
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def corrupted_news_text(value: object) -> bool:
    text = clean_news_text(value)
    if not text:
        return False
    replacement_count = text.count("\ufffd")
    suspicious_count = sum(text.count(marker) for marker in ("锟斤拷", "烫烫烫", "屯屯屯"))
    return replacement_count >= 2 or replacement_count / len(text) > 0.01 or suspicious_count > 0


def boilerplate_contact_text(value: object) -> bool:
    text = clean_news_text(value).casefold()
    matches = sum(term.casefold() in text for term in BOILERPLATE_CONTACT_TERMS)
    return matches >= 2 or ("@" in text and matches >= 1)


def article_excerpt(url: str) -> str:
    if not re.match(r"^https?://", url, re.I):
        return ""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": ARTICLE_UA})
        with urllib.request.urlopen(request, timeout=18) as response:
            raw = response.read(1_500_000)
            charset = response.headers.get_content_charset()
        page = decode_article_html(raw, charset)
        parser = ArticleMetadataParser()
        parser.feed(page)
        candidates = [clean_news_text(value) for value in parser.descriptions]
        for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
            try:
                payload = json.loads(unescape(block))
            except (json.JSONDecodeError, TypeError):
                continue
            queue = payload if isinstance(payload, list) else [payload]
            for node in queue:
                if isinstance(node, dict):
                    candidates.extend(clean_news_text(node.get(key)) for key in ("description", "articleBody"))
        paragraph_blockers = ("登录", "注册", "扫码", "下载客户端", "责任编辑", "版权声明", "违法和不良信息")
        paragraphs = [
            text for text in parser.paragraphs
            if 45 <= len(text) <= 600 and not any(blocker in text for blocker in paragraph_blockers)
        ]
        if paragraphs:
            candidates.append(" ".join(paragraphs[:3])[:600])
        candidates = [
            text for text in candidates
            if 45 <= len(text) <= 1200
            and not corrupted_news_text(text)
            and not boilerplate_contact_text(text)
        ]
        return max(candidates, key=len)[:420] if candidates else ""
    except Exception:
        return ""


def reader_news_brief(story: dict, item: dict, excerpt: str) -> tuple[str, str]:
    title = clean_news_text(story.get("title"))
    title_core = re.sub(r"\s+[-—]\s+[^-—]{2,24}$", "", title).strip()
    candidates = [(excerpt, "原文页面摘要"), (item.get("snippetOriginal", ""), "新闻聚合摘要")]
    for raw, origin in candidates:
        text = clean_news_text(raw)
        if corrupted_news_text(text) or boilerplate_contact_text(text):
            continue
        if title_core and text.startswith(title_core):
            text = text[len(title_core):].lstrip(" -—｜|：:，,。").strip()
        normalized_title = re.sub(r"\W+", "", title_core).casefold()
        normalized_text = re.sub(r"\W+", "", text).casefold()
        similarity = SequenceMatcher(None, normalized_title, normalized_text).ratio() if normalized_title and normalized_text else 0
        if len(text) >= 55 and similarity < 0.82:
            return text[:360], origin
    fallback = (
        f"公开报道显示，{title_core.rstrip('。！？!?')}。"
        "当前能够确认的信息主要来自报道标题及已公开数据；具体统计口径、适用范围和后续进展，"
        "仍需以企业公告、监管披露或原媒体更新为准。"
    )
    return fallback[:360], "公开标题与已披露信息"


def fetch_excerpts(urls: list[str]) -> dict[str, str]:
    unique = list(dict.fromkeys(urls))
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(unique) or 1)) as executor:
        futures = {executor.submit(article_excerpt, url): url for url in unique}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception:
                results[url] = ""
    return results


def fresh(item: dict, now: datetime) -> bool:
    title = item.get("titleOriginal", "")
    if re.search(r"(?:201\d|202[0-5])年?", title):
        return False
    months = {int(value) for value in re.findall(r"(?<!\d)(1[0-2]|[1-9])月", title)}
    allowed = {now.month, 12 if now.month == 1 else now.month - 1}
    if months and not months & allowed:
        return False
    quarter_map = {"一": 1, "二": 2, "三": 3, "四": 4}
    quarters = {
        int(value) if value.isdigit() else quarter_map[value]
        for value in re.findall(r"([一二三四1-4])季度", title)
    }
    current_quarter = (now.month - 1) // 3 + 1
    allowed_quarters = {current_quarter, max(1, current_quarter - 1)}
    return not quarters or bool(quarters & allowed_quarters)


def published_at(item: dict) -> datetime | None:
    raw = str(item.get("publishedAt", "")).strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=daily.CN_TZ)
    return value.astimezone(daily.CN_TZ)


def within_current_or_previous_day(item: dict, now: datetime) -> bool:
    """Accept only stories published today or yesterday in Beijing time."""
    published = published_at(item)
    if published is None:
        return False
    return published.date() in {now.date(), (now - timedelta(days=1)).date()}


def published_label(item: dict, now: datetime) -> str:
    published = published_at(item)
    if published is None:
        raise ValueError(f"missing or invalid publishedAt: {item.get('titleOriginal', '')}")
    if published.date() == now.date():
        return f"今日 {published:%H:%M}"
    if published.date() == (now - timedelta(days=1)).date():
        return f"昨日 {published:%H:%M}"
    return f"{published.month}月{published.day}日"


def editorial_topic(item: dict) -> str:
    text = f"{item.get('titleOriginal', '')} {item.get('summaryOriginal', '')}".lower()
    sales_terms = (
        "销量", "销售", "售出", "交付", "零售", "市场份额",
        "sales", "registrations", "deliveries",
    )
    decline_terms = (
        "下降", "下滑", "暴跌", "遇冷", "同比降",
        "down", "fell", "drop", "decline",
    )
    if any(term in text for term in sales_terms) and any(term in text for term in decline_terms):
        return "sales-decline"
    if "电池" in text and any(term in text for term in ("消费税", "电池税", "征税")):
        return "battery-tax"
    if "渗透率" in text:
        return "penetration-rate"
    if (
        any(term in text for term in ("汽车行业", "汽车业", "车企", "整车行业"))
        and any(term in text for term in ("利润率", "利润同比", "微利", "盈利水平"))
    ):
        return "auto-industry-profitability"
    return ""


def substantive_title(item: dict) -> bool:
    title = re.sub(r"\s+[-—]\s+[^-—]{2,16}$", "", item.get("titleOriginal", "")).strip()
    return (
        len(title) >= 7
        and title not in {"汽车出行", "汽车行业", "新能源汽车"}
        and "行业日报" not in title
        and "产业日报" not in title
        and not ("快讯" in title and "；" in title)
    )


def editorially_substantive(item: dict) -> bool:
    """Keep low-information or weakly automotive stories out of the 14-item issue."""
    title = str(item.get("titleOriginal", "")).lower()
    if any(term.lower() in title for term in WEAK_AUTO_TERMS):
        return False
    if any(term.lower() in title for term in LOW_INFORMATION_TERMS):
        return False
    # Google News RSS commonly repeats the headline in snippetOriginal. That is
    # discovery metadata rather than proof that the underlying article is thin;
    # reader_news_brief() resolves and reads the publisher page before output.
    return True


def acceptable_publisher(item: dict) -> bool:
    url = str(item.get("url", "")).lower()
    title = str(item.get("titleOriginal", ""))
    blocked_text = (
        "电子游戏", "博彩", "彩票网站", "体育投注", "开户链接",
        "官网版下载", "app下载官网", "pg电子", "电玩巴士", "配套采购/供应商",
        "汽车社区】", "互动平台-盖世汽车", "供应商_互动平台",
    )
    blocked_domains = ("tgbus.com",)
    if any(term in title.lower() for term in blocked_text) or any(domain in url for domain in blocked_domains):
        return False
    if item.get("sourceHint") == "国内汽车综合" and (
        "163.com/" in url or "手机网易网" in title
    ):
        return False
    return True


def automotive_finance_relevant(item: dict) -> bool:
    text = f"{item.get('titleOriginal', '')} {item.get('summaryOriginal', '')}".lower()
    return any(
        term in text
        for term in (
            "汽车金融", "车贷", "购车贷款", "融资租赁", "库存融资",
            "经销商资金", "经销商融资", "贴息", "首付", "汽车保险",
        )
    )


def choose(
    pool: list[dict],
    limit: int,
    topic_coverage: bool,
    minimum: int | None = None,
    source_limit: int = 2,
    against: list[dict] | None = None,
) -> list[dict]:
    minimum = limit if minimum is None else minimum
    authority_bonus = {
        "中国汽车工业协会": 80,
        "中国汽车流通协会": 80,
        "乘联会": 80,
        "重点车企": 45,
        "Reuters": 35,
        "Financial Times": 25,
    }
    priority_terms = (
        "召回", "安全", "财报", "业绩", "利润", "现金流", "渗透率", "市场分析",
        "出口", "装机量排行榜", "项目定点", "合资企业", "生产转移", "parts-supply",
        "工厂", "产能", "销量", "交付", "监管", "标准", "融资",
        "51sim", "adas供应商", "宁家服务", "长安汽车再牵手华为", "hyworldvla",
        "项目定点", "g9l开启预售", "小马智行全球自动驾驶里程",
    )
    ranked = sorted(
        pool,
        key=lambda item: (
            authority_bonus.get(item.get("sourceHint", ""), 0)
            + 12 * sum(term in str(item.get("titleOriginal", "")).lower() for term in priority_terms),
            daily.score(item),
        ),
        reverse=True,
    )
    ordered: list[dict] = []
    if topic_coverage:
        for topic in ("data", "smart", "vehicle", "supply", "industry"):
            candidate = next((item for item in ranked if daily.auto_subtopic(item) == topic and item not in ordered), None)
            if candidate:
                ordered.append(candidate)
    ordered.extend(item for item in ranked if item not in ordered)
    selected: list[dict] = []
    for item in ordered:
        comparison = selected + (against or [])
        if daily.too_similar(item, comparison):
            continue
        topic = editorial_topic(item)
        if topic and any(editorial_topic(existing) == topic for existing in comparison):
            continue
        candidate_observation = observation_preview(item)
        if any(
            SequenceMatcher(None, candidate_observation, observation_preview(existing)).ratio()
            >= OBSERVATION_SELECTION_LIMIT
            for existing in comparison
        ):
            continue
        if sum(existing["sourceHint"] == item["sourceHint"] for existing in selected) >= source_limit:
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    if len(selected) < minimum:
        raise ValueError(f"not enough independent WeChat automotive candidates: {len(selected)}/{minimum}")
    return selected


def metrics_from(story: dict) -> list[str]:
    text = f"{story.get('title', '')} {story.get('newsBrief', '')} {story.get('summary', '')}"
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
    text = f"{story.get('title', '')} {story.get('newsBrief', '')} {story.get('summary', '')}".lower()
    title_text = str(story.get("title", "")).lower()
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
    elif any(term in text for term in ("召回", "安全缺陷", "安全隐患", "故障")):
        judgment = (
            f"“{subject}”应按产品质量与监管事件处理，而不是普通舆情。{data_anchor}"
            "影响大小取决于涉及车辆范围、缺陷是否触及核心安全功能、修复方式和完成率；"
            "如果同类问题跨车型复现，质保成本与品牌信任损失会超过单次召回费用。"
        )
        watch = ["涉及车辆数", "缺陷调查结论", "召回完成率", "单车修复与质保成本"]
    elif any(term in text for term in ("收入同比", "毛利率", "期内亏损", "净利润", "ebit", "自由现金流")):
        judgment = (
            f"“{subject}”最值得看的不是收入增速本身，而是增长能否同步改善盈利与现金。{data_anchor}"
            "高增业务占比提升若伴随毛利率上升、亏损收窄，是商业化质量改善的信号；"
            "但仍要回到正式财报核对客户集中、应收和经营现金流，避免把低基数增长当成拐点。"
        )
        watch = ["分部收入与占比", "毛利率", "经营现金流", "应收账款与客户集中度"]
    elif any(term in text for term in ("装机量排行榜", "装机量排名", "供应商装机量")):
        judgment = (
            f"“{subject}”展示的是供应链份额，而不是整车销量。{data_anchor}"
            "装机量需要同时核对统计样本、车型覆盖和单车价值量；份额上升若主要来自低价车型，"
            "未必带来同幅度收入与利润，真正的壁垒还要看跨平台定点和持续供货能力。"
        )
        watch = ["统计样本与口径", "量产车型覆盖", "单车价值量", "供应商收入与毛利率"]
    elif "渗透率" in text or "月度新车销量占比" in text:
        if "出口" in text and any(term in text for term in ("零售", "国内", "淡季", "承压", "下降")):
            judgment = (
                f"“{subject}”真正反常的是国内需求承压、渗透率上升与出口高增同时发生。{data_anchor}"
                "渗透率抬升可能来自燃油车收缩更快，不等于新能源绝对销量同步增长；"
                "出口则是厂商销量的托底项，但还要用目的国注册与渠道库存验证是否卖到终端。"
            )
            watch = ["新能源零售量", "燃油车零售降幅", "出口与海外注册差", "渠道库存"]
        else:
            judgment = (
                f"“{subject}”反映的是结构变化，不是所有品牌都能同比例受益。{data_anchor}"
                "先分清全口径汽车、乘用车以及国内销量口径；渗透率上升也可能由燃油车下降更快推动，"
                "只有新能源绝对销量、价格带份额和单车利润同步改善，才能确认需求扩张。"
            )
            watch = ["新能源绝对销量", "统计口径", "分价格带份额", "新能源单车利润"]
    elif any(term in text for term in ("销量目标", "销售目标", "交付目标", "产量目标")):
        judgment = (
            f"“{subject}”中各企业目标的简单加总并不等于真实市场容量。{data_anchor}"
            "目标要成立，必须同时满足终端需求、渠道库存和产能利用率三项约束；"
            "如果零售增速跟不上批发目标，压力最终会转化为价格折让和经销商资金占用。"
        )
        watch = ["终端零售", "批零差", "渠道库存天数", "产能利用率"]
    elif any(term in title_text for term in ("产量", "生产")) and any(term in title_text for term in ("下降", "暴跌", "下滑", "推迟")):
        judgment = (
            f"“{subject}”更像供需失衡或生产切换信号，不能用常规销量增长逻辑解释。{data_anchor}"
            "需要先区分减产来自订单不足、零部件约束还是车型换代；若同时推迟新品，"
            "说明问题可能已从单月波动扩展到研发、认证或供应协同。"
        )
        watch = ["工厂产能利用率", "在手订单", "零部件缺口", "新品认证与投产节点"]
    elif any(term in text for term in ("生产从中国转移", "move production", "本地化生产")):
        judgment = (
            f"“{subject}”是产能与供应链重配，不是普通车型发布。{data_anchor}"
            "需要核对转移车型、产量、关税与物流节省能否覆盖美国制造成本上升，"
            "以及中国工厂空出的产能如何消化；只有成本、交付和利用率同时改善，迁产才有经营价值。"
        )
        watch = ["转移车型与年产量", "中美单位制造成本", "关税与物流成本", "原工厂产能利用率"]
    elif "中国" in title_text and "出口" in title_text and any(term in title_text for term in ("跃升", "增长", "百万")):
        judgment = (
            f"“{subject}”说明出口正在对冲国内零售疲软，但出口量仍不是海外终端销量。{data_anchor}"
            "应把海关或乘联分会出口与目的国注册、渠道库存和当地成交价放在一起看；"
            "若注册跟不上装运，增长可能只是库存向海外转移，不能直接等同品牌竞争力提升。"
        )
        watch = ["目的国注册量", "出口与注册差", "海外渠道库存", "区域成交价与单车利润"]
    elif "图像传感器" in text and any(term in text for term in ("工厂", "投资", "产能")):
        judgment = (
            f"“{subject}”的关键不是投资额有多大，而是新增传感器产能能否获得车载客户和合理利用率。{data_anchor}"
            "图像传感器还需区分消费电子与车规用途；只有车规认证、长期订单和良率兑现，"
            "资本开支才会转成汽车供应链能力，否则可能加重折旧与产能闲置压力。"
        )
        watch = ["车规产品占比", "主机厂与Tier1订单", "产能利用率", "良率与折旧压力"]
    elif any(term in text for term in ("销量", "销售", "售出", "交付", "产量", "零售", "出口", "市场份额", "registrations")):
        if (
            any(term in text for term in ("暴跌", "下滑", "遇冷", "下降"))
            and any(term in text for term in ("欧洲", "海外", "全球", "加拿大", "美国", "北美", "英国", "德国", "意大利", "法国", "俄罗斯", "巴西"))
        ):
            judgment = (
                f"“{subject}”反映的是海外单一区域的收缩风险，不能与出口总量增长混为一谈。"
                f"{data_anchor}应先核对当地注册量、渠道去库存、汇率和政策变化，"
                "再判断下滑来自需求转弱、供给中断还是上一年高基数；单月降幅不能直接代表全球竞争力。"
            )
            watch = ["当地终端注册量", "经销商库存天数", "汇率与售价变化", "连续三月市场份额"]
        elif "出口" in text or any(term in text for term in ("欧洲", "海外", "全球", "加拿大", "美国", "北美", "英国", "德国")):
            judgment = (
                f"“{subject}”显示中国汽车的增长空间正进一步转向海外，但出口量不等于海外零售。"
                f"{data_anchor}需要拆分整车实际注册、渠道库存和区域价格，"
                "并核对关税、本地化生产与售后网络能否支撑持续扩张。"
            )
            watch = ["海外终端注册量", "出口与零售差", "区域单车利润", "本地化产能"]
        elif any(term in text for term in ("暴跌", "下滑", "遇冷", "下降")):
            judgment = (
                f"“{subject}”需要先判断是需求收缩还是统计口径与高基数造成的表观下降。"
                f"{data_anchor}若零售、上险和经销商库存同步恶化，才说明终端压力真实存在；"
                "若主要由批发节奏变化驱动，则不宜直接外推全年市场。"
            )
            watch = ["终端上险量", "批零差", "库存预警指数", "价格折扣"]
        else:
            judgment = (
                f"“{subject}”提供了规模信号，但单一销量数字不足以判断经营质量。{data_anchor}"
                "需要区分批发、零售、出口和库存转移，并观察增长是否依赖降价；"
                "只有份额提升与单车盈利同步，规模增长才具有可持续性。"
            )
            watch = ["批发与零售差值", "出口占比", "成交均价", "单车毛利"]
    elif any(term in text for term in ("新能源市场", "市场展望")):
        judgment = (
            f"“{subject}”反映的是结构变化，不是所有品牌都能同比例受益。{data_anchor}"
            "渗透率上升后，竞争重点会从教育市场转向价格带覆盖、补能体验和存量用户复购，"
            "弱产品组合反而更容易在高渗透阶段被淘汰。"
        )
        watch = ["分价格带渗透率", "区域差异", "复购率", "新能源单车利润"]
    elif any(term in text for term in ("增程", "纯电续航", "油箱")):
        judgment = (
            f"“{subject}”不是动力路线口号之争，而是用户补能焦虑、整车成本和使用效率的取舍。"
            f"{data_anchor}增程方案是否成立，要看真实纯电使用占比、高速馈电能耗和增程器介入体验；"
            "若多数用户仍频繁用油，所谓纯电体验就没有形成产品闭环。"
        )
        watch = ["真实纯电使用占比", "馈电油耗", "增程器介入噪声", "电池与油箱成本"]
    elif any(term in text for term in ("智能驾驶", "自动驾驶", "智能网联", "机器人出租车", "行泊一体", "域控制器", "北斗", "线控", "座舱", "车载ai", "fsd", "adas", "robotaxi")):
        if any(term in text for term in ("robotaxi", "机器人出租车")):
            judgment = (
                f"“{subject}”应按运营业务而非自动驾驶演示来评估。{data_anchor}"
                "Robotaxi的关键不是单次无接管，而是限定区域内的车队利用率、安全员退出进度、"
                "事故责任和每公里成本能否共同收敛；管理层口径变化往往意味着商业化假设正在重估。"
            )
            watch = ["每万公里接管次数", "车队利用率", "安全员配置", "单公里运营成本"]
        elif "北斗" in text:
            judgment = (
                f"“{subject}”的价值在于把定位与营运监管从项目验收转成持续可用的运营能力。"
                f"{data_anchor}验收只代表阶段性交付，后续要看在线率、定位完整性、"
                "跨区域数据一致性和异常事件闭环，才能判断系统是否真正降低车队管理风险。"
            )
            watch = ["车辆在线率", "定位数据完整率", "异常闭环时长", "跨区域覆盖"]
        elif any(term in text for term in ("运维", "养车", "维修")):
            judgment = (
                f"“{subject}”补的是自动驾驶商业化中容易被忽略的车队运维环节。"
                f"{data_anchor}合作是否有价值，要看维护网络能否缩短停驶时间、标准化传感器校准，"
                "并把单车维护成本压到可复制水平，而不是只增加一个生态合作伙伴。"
            )
            watch = ["单车停驶时长", "维保网点覆盖", "传感器校准合格率", "每公里维护成本"]
        elif any(term in text for term in ("线控", "底盘")):
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
    elif (
        any(term in text for term in ("汽车行业", "汽车业", "车企", "整车行业"))
        and any(term in text for term in ("利润率", "利润同比", "微利", "盈利水平"))
    ):
        judgment = (
            f"“{subject}”说明行业规模与盈利仍在背离，不能把销量增长直接当成经营改善。"
            f"{data_anchor}利润率下行通常同时受终端降价、渠道返利、产品结构和上游成本影响，"
            "需要拆分整车厂、零部件和电池环节的利润分配，判断压力来自短期价格战还是商业模式失衡。"
        )
        watch = ["行业利润率口径", "单车毛利", "终端折扣", "经营现金流"]
    elif any(term in text for term in ("充电设施", "充电桩", "充电站", "补能网络", "换电站", "超充")):
        judgment = (
            f"“{subject}”衡量的是补能网络能否跟上电动车保有量，而不只是累计设施数量。"
            f"{data_anchor}需要拆分公共与私人设施、快充与慢充，以及城市和高速场景，"
            "并用实际利用率、故障率和高峰等待时间判断新增供给是否落在真实缺口上。"
        )
        watch = ["车桩比", "公共桩利用率", "设备在线率", "高峰平均等待时间"]
    elif any(term in text for term in ("供应链", "电池", "芯片", "零部件", "工厂", "产能", "关税", "硬件")):
        if "芯片" in text:
            judgment = (
                f"“{subject}”的门槛不只是算力参数，而是车规可靠性、工具链和长期供货承诺。"
                f"{data_anchor}芯片能否进入主机厂核心平台，要看功能安全认证、软件迁移成本、"
                "量产良率和车型生命周期内的稳定供货，奖项或样片本身还不能证明商业化。"
            )
            watch = ["车规与功能安全认证", "主机厂定点", "量产良率", "软件迁移周期"]
        elif any(term in text for term in ("磁材", "材料", "零部件")):
            judgment = (
                f"“{subject}”体现的是隐形零部件供应商的质量壁垒，而非单纯扩产故事。"
                f"{data_anchor}材料企业的议价能力取决于认证周期、产品一致性和客户平台覆盖；"
                "若收入增长仍依赖少数客户或原料价格波动，技术积累未必能直接转化为稳定利润。"
            )
            watch = ["客户平台覆盖", "认证周期", "产品良率", "客户与原料集中度"]
        else:
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

    fact_anchor = clean_news_text(story.get("newsBrief") or story.get("summary", ""))
    if len(fact_anchor) > 48:
        fact_anchor = fact_anchor[:48] + "…"
    evidence = f" 事实锚点：{fact_anchor}。" if fact_anchor else ""
    observation = f"判断：{judgment}{evidence} 验证重点：{'、'.join(watch)}。"
    return observation, watch


def observation_preview(item: dict) -> str:
    story = {
        "title": item.get("titleOriginal", ""),
        "summary": item.get("snippetOriginal", ""),
        "category": item.get("categoryHint", ""),
    }
    return professional_observation(story)[0]


def main() -> None:
    now = datetime.now(daily.CN_TZ)
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", payload)
    valid_sources = daily.FOREIGN | daily.DOMESTIC | {"重点车企"}
    base_pool = [
        item for item in candidates
        if item.get("sourceHint") in valid_sources
        and item.get("categoryHint") in {"汽车产业", "汽车金融"}
        and daily.automotive_relevant(item)
        and fresh(item, now)
        and substantive_title(item)
        and editorially_substantive(item)
        and acceptable_publisher(item)
    ]
    auto_pool = [
        item for item in base_pool
        if item["categoryHint"] == "汽车产业"
        and within_current_or_previous_day(item, now)
    ]
    finance_pool = [
        item for item in base_pool
        if item["categoryHint"] == "汽车金融"
        and automotive_finance_relevant(item)
        and within_current_or_previous_day(item, now)
    ]
    finance = choose(
        [item for item in finance_pool if item["sourceHint"] not in daily.FOREIGN],
        3,
        False,
        minimum=0,
    )
    # Keep the edition close to the 11 domestic / 3 foreign editorial target.
    # Qualified finance stories take domestic slots instead of expanding the
    # issue beyond 14 items; when finance is unavailable, fresh auto stories
    # fill those slots.
    domestic_auto = choose(
        [item for item in auto_pool if item["sourceHint"] not in daily.FOREIGN],
        11 - len(finance),
        True,
        minimum=max(7 - len(finance), 0),
        source_limit=6,
        against=finance,
    )
    foreign_auto = choose(
        [item for item in auto_pool if item["sourceHint"] in daily.FOREIGN],
        3,
        True,
        minimum=2,
        against=domestic_auto + finance,
    )
    auto = domestic_auto + foreign_auto
    selected = auto + finance
    domestic_count = sum(item["sourceHint"] not in daily.FOREIGN for item in selected)
    domestic_ratio = domestic_count / len(selected)
    if not 0.75 <= domestic_ratio <= 0.85:
        raise ValueError(f"WeChat domestic source ratio outside target range: {domestic_count}/{len(selected)}")
    stories = [daily.make_story(item, index + 30) for index, item in enumerate(selected)]
    resolved_urls = resolve_urls([item["url"] for item in selected])
    direct_urls = [resolved_urls.get(item["url"], item["url"]) for item in selected]
    excerpts = fetch_excerpts([url for url in direct_urls if not is_google_news_url(url)])
    for story, item in zip(stories, selected):
        story["publishedAt"] = item["publishedAt"]
        story["publishedLabel"] = published_label(item, now)
        original_url = item["url"]
        direct_url = resolved_urls.get(original_url, original_url)
        if is_google_news_url(direct_url):
            raise ValueError(f"WeChat publisher URL unresolved: {story['source']} / {story['title']}")
        if direct_url != original_url:
            story["aggregatorUrl"] = original_url
        story["url"] = direct_url
        story["newsBrief"], story["newsBriefSource"] = reader_news_brief(
            story,
            item,
            excerpts.get(direct_url, ""),
        )
        observation, watch = professional_observation(story)
        story["whyItMatters"] = observation
        story["watchMetrics"] = watch
    for story, item in zip(stories, selected):
        if not within_current_or_previous_day(item, now):
            raise ValueError(f"WeChat freshness validation failed: {story['title']}")
        brief = str(story.get("newsBrief", "")).strip()
        if (
            not 55 <= len(brief) <= 360
            or "<<<" in brief
            or corrupted_news_text(brief)
            or boilerplate_contact_text(brief)
        ):
            raise ValueError(f"WeChat reader news brief quality check failed: {story['title']}")
    observations = [story["whyItMatters"] for story in stories]
    if len(set(observations)) != len(observations):
        raise ValueError("WeChat professional observations must be unique")
    if any(len(observation) < 80 or "这条消息可能影响" in observation for observation in observations):
        raise ValueError("WeChat professional observation quality check failed")
    for left in range(len(observations)):
        for right in range(left + 1, len(observations)):
            similarity = SequenceMatcher(None, observations[left], observations[right]).ratio()
            if similarity > OBSERVATION_FINAL_LIMIT:
                raise ValueError(
                    "WeChat professional observations too similar: "
                    f"{left + 1}/{right + 1} ({similarity:.2f}) / "
                    f"{stories[left]['title']} / {stories[right]['title']} / "
                    f"{observations[left][:100]} / {observations[right][:100]}"
                )
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
