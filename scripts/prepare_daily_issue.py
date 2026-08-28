"""Select a genuinely fresh daily edition from runtime/candidates.json."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from google_news_url import is_google_news_url, resolve_urls

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "news.json"
CANDIDATES = ROOT / "runtime" / "candidates.json"
ARCHIVE = ROOT / "data" / "archive"
RUNTIME = ROOT / "runtime"
CN_TZ = timezone(timedelta(hours=8))

FOREIGN = {"Reuters", "BBC", "Financial Times", "The Guardian", "TechCrunch", "Electrek", "InsideEVs", "Automotive News"}
DOMESTIC = {"第一财经", "财联社", "证券时报", "36氪", "澎湃新闻", "盖世汽车", "中国汽车报", "中国汽车流通协会", "汽车之家", "经济观察报", "界面新闻", "中国房地产报", "克而瑞", "国内汽车综合", "国内房地产综合", "汽车金融", "工信部", "中国汽车工业协会", "乘联会", "懂车帝", "新出行", "亿欧汽车", "汽车商业评论", "中国银行业协会", "零壹智库", "重点车企", "百度热搜"}
QUOTAS = {"AI": 6, "科技": 5, "企业商业": 5, "财经": 5, "投资市场": 12, "房地产": 0, "汽车产业": 5, "汽车金融": 3}
EDITION_SIZE = 45
# Real-estate coverage is intentionally disabled. Auto-finance remains
# optional when no genuinely fresh story survives the quality and
# deduplication gates. Open slots are filled from the editorial fallback
# categories below; stale news is never used merely to satisfy a quota.
FLEXIBLE_MINIMUMS = {"汽车金融": 0}
FALLBACK_CATEGORIES = ("汽车产业", "企业商业", "科技", "财经")
PREFERRED = {"Reuters": 9, "BBC": 8, "Financial Times": 8, "TechCrunch": 8, "The Guardian": 7, "Electrek": 8, "InsideEVs": 8, "Automotive News": 8, "第一财经": 9, "财联社": 9, "证券时报": 8, "36氪": 8, "澎湃新闻": 7, "盖世汽车": 9, "中国汽车报": 9, "中国汽车流通协会": 8, "工信部": 10, "中国汽车工业协会": 9, "乘联会": 9, "懂车帝": 8, "新出行": 8, "亿欧汽车": 8, "汽车商业评论": 8, "百度热搜": 11}
KEYWORDS = ("AI", "人工智能", "汽车", "智能", "芯片", "算力", "科技", "财报", "利润", "订单", "股票", "市场", "融资", "房地产", "房价", "供应链", "金融", "车贷", "电池", "自动驾驶", "云", "能源")
AUTO_TERMS = ("汽车", "新车", "车型", "车企", "整车", "新能源车", "智能网联", "智能驾驶", "自动驾驶", "车载", "座舱", "三电", "电池", "充电", "经销商", "车贷", "汽车金融", "库存融资", "零部件", "供应商", "robotaxi", "tesla", "byd", "xpeng", "geely", "ford", "gm", "volkswagen", "toyota", "stellantis")
AUTO_ENGLISH = re.compile(r"\b(?:car|cars|vehicle|vehicles|automotive|automaker|automakers|ev|evs|adas|driver-assistance|electric vehicle|connected-car)\b", re.I)
AUTO_BLOCKERS = re.compile(r"\b(?:aircraft|airline|aviation|airport|ship|shipping|nike)\b", re.I)
AUTO_FOCUS_TERMS = ("上市", "发布", "首发", "亮相", "新车", "车型", "智能网联", "智能驾驶", "自动驾驶", "车载AI", "座舱", "芯片", "电池", "充电", "供应链", "零部件", "汽车金融", "车贷", "经销商", "robotaxi", "ADAS", "launch", "debut", "connected-car")
AUTO_DATA_TERMS = ("销量", "交付", "产量", "零售", "批发", "出口", "渗透率", "市场份额", "库存", "价格", "营收", "利润", "利润率", "现金流", "同比", "环比", "万辆", "%", "sales", "deliveries", "revenue", "margin", "inventory")
AUTO_FINANCIAL_TERMS = (
    "财报", "年报", "半年报", "季报", "业绩", "营收", "毛利率", "净利润",
    "税前利润", "经营现金流", "自由现金流", "单车收入", "ebit", "ebt",
    "operating profit", "gross margin", "free cash flow", "financial results",
)
DECISION_METRIC_RE = re.compile(
    r"(?:约|超|近|达|增长|下降|上涨|下跌)?\s*\d+(?:\.\d+)?\s*"
    r"(?:%|万亿元|亿元|亿美元|万元|万辆|万台|万套|万|美元|元|辆|台|家|倍)",
    re.I,
)
EXISTING_BY_URL = {}
if DATA.exists():
    for existing_story in json.loads(DATA.read_text(encoding="utf-8")).get("stories", []):
        for existing_url in (existing_story.get("url"), existing_story.get("aggregatorUrl")):
            if existing_url:
                EXISTING_BY_URL[existing_url] = existing_story


def clean_title(value: str, source: str) -> str:
    value = re.sub(r"\s+-\s+(Reuters|Financial Times|第一财经|财联社|证券时报|36 Kr|Jiemian\.com)\s*$", "", value).strip()
    return value or f"{source}最新报道"


def automotive_relevant(item: dict) -> bool:
    text = f"{item.get('titleOriginal', '')} {item.get('snippetOriginal', '')}"
    if AUTO_BLOCKERS.search(text):
        return False
    lowered = text.lower()
    return any(term.lower() in lowered for term in AUTO_TERMS) or bool(AUTO_ENGLISH.search(text))


def title_tokens(item: dict) -> set[str]:
    text = item.get("titleOriginal", "").lower()
    latin = {token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 2}
    chinese = set(re.findall(r"[\u4e00-\u9fff]{2,6}", text))
    return latin | chinese


def too_similar(item: dict, selected: list[dict]) -> bool:
    tokens = title_tokens(item)
    for other in selected:
        other_tokens = title_tokens(other)
        if tokens and other_tokens and len(tokens & other_tokens) / min(len(tokens), len(other_tokens)) >= 0.55:
            return True
    return False


def auto_subtopic(item: dict) -> str:
    text = f"{item.get('titleOriginal', '')} {item.get('snippetOriginal', '')}".lower()
    if any(term.lower() in text for term in ("智能网联", "车载ai", "智能驾驶", "自动驾驶", "座舱", "芯片", "robotaxi", "adas", "connected-car", "software")):
        return "smart"
    if any(term.lower() in text for term in AUTO_DATA_TERMS):
        return "data"
    if any(term.lower() in text for term in ("新车", "上市", "首发", "亮相", "车型", "特斯拉", "理想", "蔚来", "小鹏", "小米", "比亚迪", "launch", "debut", "model")):
        return "vehicle"
    if any(term.lower() in text for term in ("供应链", "电池", "充电", "零部件", "产能", "工厂", "成本", "关税", "supply chain", "battery", "charging")):
        return "supply"
    return "industry"


def diverse_auto_order(choices: list[dict]) -> list[dict]:
    ordered = []
    for topic in ("data", "smart", "vehicle", "supply"):
        candidate = next((item for item in choices if auto_subtopic(item) == topic and item not in ordered), None)
        if candidate:
            ordered.append(candidate)
    ordered.extend(item for item in choices if item not in ordered)
    return ordered


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
    if item.get("categoryHint") in {"汽车产业", "汽车金融"}:
        relevance += sum(4 for word in AUTO_FOCUS_TERMS if word.lower() in text.lower())
        relevance += sum(6 for word in AUTO_DATA_TERMS if word.lower() in text.lower())
        financial_hits = sum(1 for word in AUTO_FINANCIAL_TERMS if word.lower() in text.lower())
        relevance += min(32, financial_hits * 8)
    snippet = item.get("snippetOriginal", "")
    quality = min(len(snippet), 500) / 100
    if item.get("discoverySource") == "百度热搜":
        rank = int(item.get("hotRank") or 50)
        relevance += max(0, 18 - rank)
    return (PREFERRED.get(item.get("sourceHint"), 1) + relevance + quality, item.get("publishedAt", ""))


def has_sufficient_foreign_source(item: dict) -> bool:
    """Reject foreign candidates whose source snippet cannot support bilingual copy."""
    if item.get("sourceHint") not in FOREIGN:
        return True
    source_text = str(item.get("snippetOriginal") or "").strip()
    source_words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", source_text)
    return len(source_words) >= 8


def published_datetime(item: dict) -> datetime | None:
    value = str(item.get("publishedAt", "")).strip()
    if not value:
        return None
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published.astimezone(CN_TZ)


def freshness_limit(item: dict) -> timedelta:
    return timedelta(days=7) if item.get("categoryHint") == "汽车金融" else timedelta(hours=48)


def fresh_for_website(item: dict, now: datetime) -> bool:
    published = published_datetime(item)
    if published is None:
        return False
    age = now - published
    return -timedelta(minutes=10) <= age <= freshness_limit(item)


def published_label(item: dict, now: datetime) -> str:
    published = published_datetime(item)
    if published is None:
        raise ValueError(f"missing or invalid publishedAt: {item.get('titleOriginal', '')}")
    if published.date() == now.date():
        return f"今日 {published:%H:%M}"
    if published.date() == (now - timedelta(days=1)).date():
        return f"昨日 {published:%H:%M}"
    return f"{published.month}月{published.day}日 {published:%H:%M}"


def archived_urls_before(cutoff: datetime) -> set[str]:
    urls: set[str] = set()
    for archive_path in sorted(ARCHIVE.glob("*.json")):
        if archive_path.name == "index.json":
            continue
        try:
            archive_date = datetime.strptime(archive_path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if archive_date >= cutoff.date():
            continue
        try:
            archive = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for story in archive.get("stories", []):
            urls.update(
                url
                for url in (story.get("url"), story.get("aggregatorUrl"))
                if url
            )
    return urls


def select(candidates: list[dict], old_urls: set[str], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(CN_TZ)
    current_year = now.year
    current_month = now.month
    allowed_months = {current_month, 12 if current_month == 1 else current_month - 1}
    stale_year = re.compile(r"(?:201\d|202[0-5])年?") if current_year == 2026 else re.compile(r"$^")
    def stale_month(item: dict) -> bool:
        months = {int(value) for value in re.findall(r"(?<!\d)(1[0-2]|[1-9])月", item.get("titleOriginal", ""))}
        return bool(months and not months & allowed_months)
    def observation_preview(item: dict) -> str:
        return decision_note({
            "title": item.get("titleOriginal", ""),
            "summary": item.get("snippetOriginal", ""),
            "category": item.get("categoryHint", ""),
        })
    def observation_too_similar(item: dict, selected: list[dict]) -> bool:
        preview = observation_preview(item)
        return any(
            SequenceMatcher(None, preview, observation_preview(existing)).ratio() >= 0.80
            for existing in selected
        )
    pool = [
        x for x in candidates
        if x.get("url") not in old_urls
        and x.get("sourceHint") in FOREIGN | DOMESTIC
        and x.get("categoryHint") in QUOTAS
        and fresh_for_website(x, now)
        and has_sufficient_foreign_source(x)
        and not stale_year.search(x.get("titleOriginal", ""))
        and not stale_month(x)
        and (x.get("categoryHint") not in {"汽车产业", "汽车金融"} or automotive_relevant(x))
    ]
    picked, used = [], set()
    for category, quota in QUOTAS.items():
        choices = sorted((x for x in pool if x["categoryHint"] == category), key=score, reverse=True)
        foreign_target = quota // 2
        domestic_target = quota - foreign_target
        for group, target in ((FOREIGN, foreign_target), (DOMESTIC, domestic_target)):
            group_choices = [x for x in choices if x["sourceHint"] in group]
            if category == "汽车产业":
                group_choices = diverse_auto_order(group_choices)
            for item in group_choices:
                category_picked = [x for x in picked if x["categoryHint"] == category]
                if item["url"] in used or too_similar(item, category_picked) or observation_too_similar(item, picked):
                    continue
                if category in {"汽车产业", "汽车金融"} and sum(x["sourceHint"] == item["sourceHint"] for x in category_picked) >= 2:
                    continue
                picked.append(item); used.add(item["url"])
                if sum(1 for x in picked if x["categoryHint"] == category and x["sourceHint"] in group) >= target:
                    break
        while sum(1 for x in picked if x["categoryHint"] == category) < quota:
            category_picked = [x for x in picked if x["categoryHint"] == category]
            item = next((x for x in choices if x["url"] not in used and not too_similar(x, category_picked) and not observation_too_similar(x, picked) and (category not in {"汽车产业", "汽车金融"} or sum(y["sourceHint"] == x["sourceHint"] for y in category_picked) < 2)), None)
            if not item:
                minimum = FLEXIBLE_MINIMUMS.get(category, quota)
                if len(category_picked) >= minimum:
                    break
                raise ValueError(f"not enough fresh candidates for {category}: {len(category_picked)}/{minimum}")
            picked.append(item); used.add(item["url"])
    target_total = EDITION_SIZE
    while len(picked) < target_total:
        filler = None
        for category in FALLBACK_CATEGORIES:
            category_picked = [x for x in picked if x["categoryHint"] == category]
            choices = sorted((x for x in pool if x["categoryHint"] == category), key=score, reverse=True)
            if category == "汽车产业":
                choices = diverse_auto_order(choices)
            filler = next(
                (
                    x for x in choices
                    if x["url"] not in used
                    and not too_similar(x, category_picked)
                    and not observation_too_similar(x, picked)
                    and (
                        category != "汽车产业"
                        or sum(y["sourceHint"] == x["sourceHint"] for y in category_picked) < 2
                    )
                ),
                None,
            )
            if filler:
                break
        if not filler:
            raise ValueError(f"not enough fresh candidates to fill edition: {len(picked)}/{target_total}")
        picked.append(filler); used.add(filler["url"])
    if len(picked) != target_total:
        raise ValueError(f"selection count mismatch: {len(picked)}")
    return picked


def decision_metrics(story: dict) -> list[str]:
    text = f"{story.get('title', '')} {story.get('summary', '')}"
    values = []
    for value in DECISION_METRIC_RE.findall(text):
        cleaned = re.sub(r"\s+", "", value)
        if cleaned not in values:
            values.append(cleaned)
    return values[:3]


def decision_note(story: dict) -> str:
    title = str(story.get("title", "")).strip()
    summary = re.sub(r"\s+", " ", str(story.get("summary", ""))).strip()
    display_title = re.sub(r"\s+[-—]\s+[^-—]{2,20}$", "", title).strip()
    display_summary = re.sub(r"\s+[-—]\s+[^-—]{2,20}$", "", summary).strip()
    category = story.get("category", "")
    text = f"{title} {summary}".lower()
    subject = display_title if len(display_title) <= 34 else display_title[:33] + "…"
    metrics = decision_metrics(story)
    data = f"先核对报道中的{'、'.join(metrics)}采用什么统计口径；" if metrics else ""
    openings = (
        f"这条新闻真正要看的不是标题，而是“{subject}”会不会改变业务结果。",
        f"把“{subject}”放进经营里看，关键不在声量，而在结果能否兑现。",
        f"对决策最有用的信息，是“{subject}”背后的约束条件。",
        f"别急着顺着“{subject}”下结论，先看它通过哪条路径影响经营。",
    )
    opening = openings[sum(ord(char) for char in title) % len(openings)]

    if category == "AI":
        if any(term in text for term in ("政治", "特朗普", "政府", "选举", "争议")):
            core = "这类消息对AI业务的直接影响有限，更值得看的是创始人言论会不会转化为监管摩擦、品牌风险或关键客户态度变化。"
            watch = "观察政府合同、监管动作、客户流失和公司治理是否出现实质变化；没有这些变化，就不必把政治表态当成经营拐点。"
        elif any(term in text for term in ("重聚", "家人", "寻亲", "个人故事")):
            core = "这是产品进入真实生活场景的案例，但个案感染力不能代替规模证据；价值在于AI是否解决了传统工具难以完成的信息整理和线索匹配。"
            watch = "后续看类似任务的成功率、隐私保护、人工核验和用户是否持续使用。"
        elif any(term in text for term in ("就业", "岗位", "劳动力", "裁员", "招聘", "失业")):
            core = "AI对就业的影响不会平均发生，最先变化的是可标准化任务、初级岗位数量和团队人效，而不是某个职业一夜消失。"
            watch = "盯住企业实际招聘、每名员工产出和AI工具使用率，三项同时变化才算结构性替代。"
        elif any(term in text for term in ("数据中心", "电力", "算力", "芯片", "资本开支", "capex")):
            core = "算力扩张能否成立，取决于电力、折旧和推理成本能否被真实收入覆盖，宣布投资规模本身不等于形成回报。"
            watch = "重点看上架率、单位推理成本、付费客户增速和资本开支回收期。"
        elif any(term in text for term in ("监管", "版权", "隐私", "安全", "诉讼", "法案")):
            core = "规则变化会直接抬高数据取得、模型训练和产品上线的合规成本，也可能重新划分平台与内容方的议价权。"
            watch = "后续看正式条款、适用范围、整改期限和企业是否调整产品功能。"
        elif any(term in text for term in ("融资", "估值", "投资", "收购")):
            core = "融资证明资本愿意下注，不证明产品已经找到稳定需求；高估值会把收入增长和毛利兑现压力提前。"
            watch = "更值得跟踪的是年度经常性收入、客户续费、现金消耗速度和下一轮融资条件。"
        elif any(term in text for term in ("模型", "助手", "智能体", "chatgpt", "claude", "发布")):
            core = "模型能力只有转成高频使用、付费转化和更低交付成本，才会形成产品壁垒；榜单领先通常维持不了太久。"
            watch = "观察活跃用户、任务完成率、续费率以及每次有效任务的推理成本。"
        else:
            core = "这更像一个AI使用场景信号，不能直接外推成行业增长；需要区分一次性尝鲜、真实效率提升和长期付费意愿。"
            watch = "看用户是否持续使用、是否愿意付费，以及风险和人工复核成本有没有同步上升。"
    elif category == "科技":
        if any(term in text for term in ("芯片", "半导体", "传感器", "硬件")):
            core = "技术参数领先只是起点，商业价值要经过良率、认证、客户导入和量产成本四道关。"
            watch = "后续关注量产时间、客户定点、良率爬坡和单颗毛利，而不是只看实验室指标。"
        elif any(term in text for term in ("融资", "天使轮", "a轮", "投资")):
            core = "早期融资解决的是生存时间，不是商业模式；真正的分水岭是能否把试用客户变成可续费收入。"
            watch = "判断时看现金跑道、付费客户数、客单价和获客成本是否改善。"
        elif any(term in text for term in ("安全", "漏洞", "攻击", "故障")):
            core = "安全事件的严重性取决于影响范围、数据敏感度和修复速度，单看厂商声明容易低估后续成本。"
            watch = "核对受影响用户、补丁完成率、监管通报和客户流失情况。"
        else:
            core = "新技术能否成为生意，要看它是否解决高频痛点，并在性能、成本和切换门槛之间形成明确优势。"
            watch = "下一步看真实部署、客户复购、交付周期和毛利，而不是发布会上的功能数量。"
    elif category == "企业商业":
        if any(term in text for term in ("营收", "利润", "财报", "亏损", "毛利")):
            core = "财务数字要拆成增长来源和利润质量：涨价、并表和一次性收益，含金量都低于核心业务量价齐升。"
            watch = "把收入增速、经营现金流、毛利率和管理层指引放在一起看。"
        elif any(term in text for term in ("裁员", "重组", "合并", "收购", "出售")):
            core = "组织调整可以降成本，也可能伤害交付和客户关系；真正效果要看节省费用是否超过整合损耗。"
            watch = "关注重组费用、员工流失、客户续约和调整后的利润率。"
        elif any(term in text for term in ("订单", "签约", "合作", "中标")):
            core = "签约不是收入，关键是合同金额、履约周期、回款条件和客户是否有取消权。"
            watch = "后续用订单转收入比例、应收账款和现金回款验证合作质量。"
        else:
            core = "企业动作是否重要，要看它能否带来新增客户、提高议价权或降低长期成本，而不是短期曝光。"
            watch = "跟踪客户数、客单价、交付效率和经营现金流的实际变化。"
    elif category == "财经":
        if any(term in text for term in ("利率", "降息", "降准", "通胀", "cpi", "货币")):
            core = "宏观政策不会直接变成增长，必须经过资金成本、信用投放和居民企业需求三层传导。"
            watch = "看市场利率、信贷结构、企业融资和终端需求是否同步改善。"
        elif any(term in text for term in ("银行", "贷款", "不良", "信贷", "金融公司")):
            core = "金融规模增长是否健康，取决于资金成本、资产收益和坏账三者的平衡，不能只看余额。"
            watch = "重点核对净息差、不良生成率、拨备覆盖和逾期迁徙。"
        elif any(term in text for term in ("政策", "监管", "改革", "规则")):
            core = "政策信号和实际效果之间隔着执行细则、地方落实和市场主体响应，方向正确不等于马上见效。"
            watch = "后续看正式文件、实施时间、覆盖对象和第一批真实业务数据。"
        else:
            core = "这类财经信息要区分短期情绪与中期基本面，单一数字通常不能说明经济拐点。"
            watch = "结合连续月份数据、结构分项和企业现金流判断趋势是否成立。"
    elif category == "投资市场":
        if any(term in text for term in ("财报", "营收", "利润", "业绩", "指引")):
            core = "市场交易的是业绩相对预期的差，而不是数字绝对好坏；好业绩若早已计价，也可能不涨。"
            watch = "比较实际结果、市场一致预期、下一期指引和估值位置。"
        elif any(term in text for term in ("上涨", "下跌", "暴涨", "暴跌", "新高", "跳水")):
            core = "价格异动先说明资金和预期在变，不等于基本面已经改变；追着涨跌解释很容易倒因为果。"
            watch = "核对成交量、资金流、事件持续性和盈利预期是否真的调整。"
        elif any(term in text for term in ("债券", "收益率", "国债", "美元", "汇率")):
            core = "利率和汇率变化会通过估值折现、融资成本和跨境资金流影响资产，但不同板块敏感度差异很大。"
            watch = "看期限利差、实际利率、美元流动性和企业盈利暴露。"
        else:
            core = "这条消息能否形成投资逻辑，要回答盈利是否改变、市场是否已计价、风险回报是否仍合算三个问题。"
            watch = "不要只看事件方向，继续跟踪盈利预测、估值和资金行为。"
    elif category == "房地产":
        if any(term in text for term in ("房价", "销售", "成交", "库存", "去化")):
            core = "楼市是否企稳要同时看量、价和库存；单月成交回升如果依赖大幅折价，不能算真正复苏。"
            watch = "盯住新房与二手房成交、价格折扣、去化周期和土地市场。"
        elif any(term in text for term in ("债", "融资", "违约", "偿债", "现金流")):
            core = "地产信用风险的核心是项目现金回笼能否覆盖到期债务，融资消息本身只能缓解时间压力。"
            watch = "核对销售回款、受限现金、到期债务和融资成本。"
        elif any(term in text for term in ("政策", "降准", "利率", "救市", "限购")):
            core = "政策效果取决于能否降低购房门槛并修复收入预期；资金更便宜，不代表居民马上加杠杆。"
            watch = "看按揭利率、首付比例、来访转化和政策后连续成交数据。"
        else:
            core = "地产信息要落到项目和城市层面，全国口径容易掩盖区域、产品和企业信用的巨大差异。"
            watch = "继续看所在城市库存、项目去化、开发商现金流和交付进度。"
    elif category == "汽车产业":
        if any(term in text for term in ("销量", "交付", "产量", "零售", "出口", "份额")):
            core = "销量增长不等于经营变好，要区分批发、零售、出口和库存转移，还要看是否靠降价换量。"
            watch = "判断质量时同时看批零差、成交均价、库存天数和单车毛利。"
        elif any(term in text for term in ("智能驾驶", "自动驾驶", "座舱", "fsd", "传感器", "芯片")):
            core = "智能化价值不在功能演示，而在能否安全量产、被用户持续使用，并把单车成本转成收入或溢价。"
            watch = "后续看车型定点、装车量、用户使用率、接管数据和硬件成本。"
        elif any(term in text for term in ("电池", "供应链", "零部件", "产能", "工厂", "关税")):
            core = "供应链变化首先影响BOM成本、交付连续性和资本占用；自研并不天然比外采更划算。"
            watch = "核对良率、产能利用率、替代验证周期和真实成本节省。"
        elif any(term in text for term in ("裁员", "重组", "合资", "亏损", "利润")):
            core = "车企调整的本质是重新寻找规模与盈利的平衡，砍成本如果同时伤害新品和渠道，效果会反噬销量。"
            watch = "看固定成本下降、产能利用率、新品节奏和经销商库存。"
        else:
            core = "汽车新闻要从产品声量回到订单、交付、成本和渠道；没有这些数据，发布动作还不能证明竞争力。"
            watch = "继续跟踪真实订单、交付爬坡、成交价格和用户口碑。"
    elif category == "汽车金融":
        if any(term in text for term in ("不良", "逾期", "资产规模", "贷款")):
            core = "汽车金融不能只看规模和低不良率，还要看新增贷款质量、资金成本以及风险是否被宽限期暂时掩盖。"
            watch = "核对首期逾期、30天以上逾期、净息差、拨备和经销商敞口。"
        elif any(term in text for term in ("首付", "贴息", "利率", "车贷")):
            core = "低首付和贴息能拉动成交，也会提高贷款价值比；促销力度必须和客户偿付能力一起看。"
            watch = "关注实际年化利率、审批通过率、提前还款和首期逾期。"
        else:
            core = "这条信息先要确认是否真属于汽车金融，而不是把车企股价或普通汽车新闻误当金融业务。"
            watch = "后续必须看到贷款、租赁、库存融资、保险或经销商资金的明确数据。"
    else:
        core = "这条消息的价值取决于它是否改变需求、成本、竞争位置或现金流，而不是短期讨论热度。"
        watch = "继续用正式披露和后续经营数据验证。"

    fact = display_summary[:56] + ("…" if len(display_summary) > 56 else "")
    return f"{opening}{data}{core}报道给出的事实锚点是：{fact}。{watch}"


INSIGHT_THEMES = (
    {
        "key": "auto_profit", "categories": {"汽车产业"},
        "terms": ("销量", "交付", "出口", "市场份额", "利润", "亏损", "价格", "毛利"),
        "headline": "汽车规模扩张与单车利润重新校准",
        "claim": "车企需要证明销量和份额不是靠过度降价与渠道压库换来的，规模只有同时改善单车利润和现金回款才有价值",
        "signals": ("汽车销量质量", "单车利润", "渠道库存"),
    },
    {
        "key": "auto_smart", "categories": {"汽车产业"},
        "terms": ("智能驾驶", "自动驾驶", "座舱", "芯片", "传感器", "fsd", "电池", "供应链"),
        "headline": "汽车智能化进入量产与成本验证",
        "claim": "智能化和供应链投入要从功能展示走向车型定点、稳定交付与可回收的单车成本",
        "signals": ("智能化量产", "供应链成本", "用户使用率"),
    },
    {
        "key": "ai_work", "categories": {"AI"},
        "terms": ("就业", "岗位", "劳动力", "裁员", "招聘", "工作", "效率", "员工"),
        "headline": "AI就业争论回到真实人效",
        "claim": "企业是否减少岗位不是唯一答案，更重要的是AI有没有提高一线员工产出、降低错误率并保住组织能力",
        "signals": ("AI人效", "岗位变化", "工具使用率"),
    },
    {
        "key": "ai_infra", "categories": {"AI", "科技"},
        "terms": ("数据中心", "算力", "电力", "芯片", "资本开支", "基础设施", "能源"),
        "headline": "AI算力扩张面对能源与回报约束",
        "claim": "数据中心和芯片投资最终要由利用率、推理收入和电力成本共同验证，建设规模本身不能代表商业回报",
        "signals": ("AI资本开支", "电力约束", "推理成本"),
    },
    {
        "key": "ai_governance", "categories": {"AI", "科技"},
        "terms": ("安全", "黑客", "监管", "版权", "隐私", "失控", "诉讼", "道歉"),
        "headline": "AI能力扩张同步抬高治理成本",
        "claim": "能力越强，企业越需要把权限边界、人工复核和事故责任写进产品，而不是把风险留给用户承担",
        "signals": ("AI安全", "合规成本", "人工复核"),
    },
    {
        "key": "market_earnings", "categories": {"投资市场", "企业商业", "科技"},
        "terms": ("财报", "营收", "利润", "业绩", "指引", "收入增长", "财报季"),
        "headline": "财报季开始检验科技投入含金量",
        "claim": "市场会重新比较AI投入、收入增速和利润率，只有资本开支转成可持续订单，估值才能得到基本面支撑",
        "signals": ("科技财报", "盈利指引", "估值重定价"),
    },
    {
        "key": "market_rates", "categories": {"投资市场", "财经"},
        "terms": ("利率", "加息", "降息", "收益率", "美元", "汇率", "通胀", "央行"),
        "headline": "利率预期重新牵动资产定价",
        "claim": "利率路径会同时改变融资成本、估值折现和跨境资金流，单次政策信号需要用连续数据确认",
        "signals": ("利率路径", "资金成本", "市场定价"),
    },
    {
        "key": "property", "categories": {"房地产"},
        "terms": ("房价", "成交", "销售", "库存", "去化", "融资", "地产债", "救市"),
        "headline": "房地产修复继续看量价与现金流",
        "claim": "政策和成交回升只有同时改善价格、库存去化和开发商回款，才说明市场开始形成自我修复",
        "signals": ("楼市成交", "去化周期", "地产现金流"),
    },
    {
        "key": "auto_finance", "categories": {"汽车金融", "财经"},
        "terms": ("汽车金融", "车贷", "不良", "逾期", "首付", "贴息", "保值率"),
        "headline": "汽车金融在增长与风险间找平衡",
        "claim": "金融渗透和资产规模要与资金成本、逾期表现和车辆残值一起看，促销不能掩盖信用风险",
        "signals": ("汽车金融", "资金成本", "逾期风险"),
    },
)


def insight_subject(story: dict) -> str:
    title = re.sub(r"\s+[-—]\s+[^-—]{2,20}$", "", str(story.get("title", ""))).strip()
    return title if len(title) <= 30 else title[:29] + "…"


def build_daily_insight(stories: list[dict], previous: dict) -> dict:
    ranked_themes = []
    for theme in INSIGHT_THEMES:
        candidates = []
        for position, story in enumerate(stories):
            if story.get("category") not in theme["categories"]:
                continue
            text = f"{story.get('title', '')} {story.get('summary', '')}".lower()
            hits = sum(term.lower() in text for term in theme["terms"])
            if not hits:
                continue
            story_score = hits * 4 + len(decision_metrics(story)) * 2 + (5 if story.get("isTop") else 0) + max(0, 3 - position // 6)
            candidates.append((story_score, story))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        representative = candidates[0][1]
        theme_score = candidates[0][0] + min(6, len(candidates) * 2)
        ranked_themes.append((theme_score, theme, representative))
    ranked_themes.sort(key=lambda item: item[0], reverse=True)
    chosen = ranked_themes[:3]
    if len(chosen) < 2:
        fallback = []
        seen = set()
        for story in stories:
            if story["category"] in seen:
                continue
            seen.add(story["category"])
            fallback.append((0, {
                "headline": f"{story['category']}进入事实验证",
                "claim": "当天信息需要用后续经营数据确认，不能只按标题判断趋势",
                "signals": (story["category"],),
            }, story))
            if len(chosen) + len(fallback) >= 3:
                break
        chosen.extend(fallback)
    title = "，".join(item[1]["headline"] for item in chosen[:2])
    body_parts = [
        f"围绕“{insight_subject(story)}”，{theme['claim']}"
        for _, theme, story in chosen[:3]
    ]
    body = "今天的判断来自三条具体线索：" + "；".join(body_parts) + "。"
    signals = []
    for _, theme, _ in chosen:
        for signal in theme["signals"]:
            if signal not in signals:
                signals.append(signal)
            if len(signals) == 5:
                break
        if len(signals) == 5:
            break
    insight = {"title": title, "body": body, "signals": signals}
    previous_insight = previous.get("dailyInsight", {})
    old_text = f"{previous_insight.get('title', '')} {previous_insight.get('body', '')}"
    new_text = f"{title} {body}"
    if old_text and SequenceMatcher(None, old_text, new_text).ratio() > 0.82:
        lead = insight_subject(stories[0])
        insight["title"] = f"{chosen[0][1]['headline']}：{lead}成为今日验证点"
        insight["body"] = body + f" 今天的首要事实锚点是“{lead}”，后续判断必须回到对应数据。"
    return insight


def detail_body(story: dict, deep: bool = False) -> str:
    source, category = story["source"], story["category"]
    summary, why = story["summary"], story["whyItMatters"]
    text = (
        f"事实进展：据{source}最新公开报道，{summary} 目前能够确认的信息以原报道、企业公告或监管披露为边界；报道未给出的合同条款、财务数字和执行时间表，不作补充推测。\n"
        f"影响路径：这项变化可能通过{category}领域的产品需求、成本结构、订单兑现、资本开支或竞争关系传导。判断其重要性不能只看标题和短期价格反应，而要观察相关主体是否真正改变业务安排，以及客户和供应链是否出现可验证的响应。\n"
        f"决策含义：{why} 对企业经营者，应分别记录已经发生的事实、管理层目标和市场预期；对个人投资者，还需要结合估值、现金流与风险承受能力，避免由单条新闻直接推导长期趋势。\n"
        f"待核验事项：后续应检查更完整的数字、实施范围、正式时间表、监管文件和财务披露，并观察影响是否进入交付、利润率、融资成本、现金流或资产价格。本文仅依据{source}及公开资料整理，不构成投资建议，最终以权威披露为准。"
    )
    return text[:1000]


def make_story(item: dict, index: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(CN_TZ)
    selection_source = item["sourceHint"]
    source = str(item.get("publisherHint") or selection_source).strip()
    original_title = clean_title(item.get("titleOriginal", ""), source)
    if source == "重点车企":
        publisher = re.search(r"\s+-\s+([^-]+)$", original_title)
        if publisher:
            source = publisher.group(1).strip()
            original_title = original_title[:publisher.start()].strip()
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
    if item.get("discoverySource") == "百度热搜" and item.get("trendTitle"):
        title = str(item["trendTitle"]).strip()
    if title == original_title and is_foreign:
        title = f"{source}报道：{original_title}"
    story = {
        "title": title, "summary": summary,
        "source": source, "category": item["categoryHint"], "url": item["url"],
        "publishedAt": published_datetime(item).isoformat(),
        "publishedLabel": published_label(item, now), "isTop": index < 20,
    }
    for key in ("discoverySource", "hotRank", "hotScore", "trendTitle", "trendDescription"):
        if item.get(key) not in (None, ""):
            story[key] = item[key]
    story["whyItMatters"] = decision_note(story)
    why = story["whyItMatters"]
    if story["category"] == "投资市场":
        story.update({"market": "海外资本市场" if is_foreign else "中国资本市场", "sentiment": "中性观察", "horizon": "短中期跟踪", "riskNote": "市场价格受消息、流动性和后续披露共同影响，本文不构成投资建议。"})
    story["detailBody"] = detail_body(story, index < 20)
    story["keyFacts"] = [
        f"信息来源为{source}，报道主题为“{title}”。", summary,
        f"本条归入“{story['category']}”栏目，发布时间为{story['publishedLabel']}。", why,
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
    old_urls = archived_urls_before(now)
    resolved_urls: dict[str, str] = {}
    for _ in range(6):
        selected = select(candidates, old_urls, now)
        resolved_urls = resolve_urls([item["url"] for item in selected])
        repeated_aggregators = {
            item["url"]
            for item in selected
            if resolved_urls.get(item["url"], item["url"]) in old_urls
        }
        # Different feed entries (or a publisher entry plus a Google News
        # wrapper) can resolve to the same article. Keep the first selected
        # occurrence and block later wrappers so the next selection fills the
        # vacated slots with genuinely distinct stories.
        seen_direct_urls: set[str] = set()
        for item in selected:
            direct_url = resolved_urls.get(item["url"], item["url"])
            if direct_url in seen_direct_urls:
                repeated_aggregators.add(item["url"])
            else:
                seen_direct_urls.add(direct_url)
        if not repeated_aggregators:
            break
        # A Google News wrapper can change while resolving to a publisher URL
        # already present in the archive. Block that wrapper and reselect so a
        # fresh alternative is used instead of failing the whole edition.
        old_urls.update(repeated_aggregators)
    else:
        raise ValueError("unable to select an edition without archived publisher URLs")
    top_foreign = sorted((x for x in selected if x["sourceHint"] in FOREIGN), key=score, reverse=True)[:10]
    top_domestic = sorted((x for x in selected if x["sourceHint"] in DOMESTIC), key=score, reverse=True)[:10]
    top_urls = {x["url"] for x in top_foreign + top_domestic}
    selected = [item for pair in zip(top_foreign, top_domestic) for item in pair] + [x for x in selected if x["url"] not in top_urls]

    RUNTIME.mkdir(exist_ok=True)
    backup = RUNTIME / f"news-before-{now:%Y-%m-%d-%H%M%S}.json"
    backup.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    same_day = str(current.get("dateLabel", "")).startswith(f"{now.year}年{now.month}月{now.day}日")
    issue = int(current.get("issue", 0)) if same_day else int(current.get("issue", 0)) + 1
    stories = [make_story(item, i, now) for i, item in enumerate(selected)]
    for story, item in zip(stories, selected):
        aggregator_url = item["url"]
        direct_url = resolved_urls.get(aggregator_url, aggregator_url)
        if is_google_news_url(direct_url):
            raise ValueError(f"website publisher URL unresolved: {story['source']} / {story['title']}")
        if direct_url != aggregator_url:
            story["aggregatorUrl"] = aggregator_url
        story["url"] = direct_url
    # Translation can make two foreign stories converge after selection even
    # when their source-language previews were sufficiently distinct.  Keep
    # the quality gate, but ground the later note in its own reported fact so
    # the edition does not fail merely because a category template repeats.
    for right, story in enumerate(stories):
        for left in range(right):
            if SequenceMatcher(
                None,
                stories[left]["whyItMatters"],
                story["whyItMatters"],
            ).ratio() <= 0.80:
                continue
            anchor = re.sub(r"\s+", " ", str(story.get("summary", ""))).strip()
            if anchor:
                title_anchor = re.sub(r"\s+", " ", str(story.get("title", ""))).strip()
                story["whyItMatters"] = (
                    f"围绕“{title_anchor[:52]}”，当前可确认的事实是："
                    f"{anchor[:160].rstrip('，。；;')}。"
                    "这条信息的决策价值取决于上述事实能否继续转化为可核验的业务结果；"
                    "后续应优先追踪正式披露、执行进度、客户响应及其对收入、利润与现金流的实际影响。"
                )
                story["detailBody"] = detail_body(story, right < 20)
                story["keyFacts"][-1] = story["whyItMatters"]
    notes = [story["whyItMatters"] for story in stories]
    if len(set(notes)) != len(notes) or any(len(note) < 90 for note in notes):
        raise ValueError("website decision-note uniqueness or depth validation failed")
    max_similarity = 0.0
    max_pair = (0, 0)
    for left in range(len(notes)):
        for right in range(left + 1, len(notes)):
            similarity = SequenceMatcher(None, notes[left], notes[right]).ratio()
            if similarity > max_similarity:
                max_similarity, max_pair = similarity, (left + 1, right + 1)
    if max_similarity > 0.82:
        raise ValueError(
            f"website decision notes too similar: {max_pair[0]}/{max_pair[1]} ({max_similarity:.2f})"
        )
    overlap = sum(1 for s in stories if s["url"] in old_urls)
    if overlap / len(stories) > 0.2:
        raise ValueError(f"cross-day overlap too high: {overlap}/{len(stories)}")
    data = {
        "dateLabel": f"{now.year}年{now.month}月{now.day}日 星期{'一二三四五六日'[now.weekday()]}",
        "issue": issue, "statusLabel": f"本次内容完成 · {now:%H:%M}", "defaultCategory": "AI",
        "dailyInsight": build_daily_insight(stories, previous),
        "sources": sorted({s["source"] for s in stories}), "stories": stories,
    }
    previous_insight = previous.get("dailyInsight", {})
    if previous_insight and data["dailyInsight"] == previous_insight:
        raise ValueError("daily insight must differ from the previous issue")
    if len(data["dailyInsight"]["signals"]) < 4 or len(data["dailyInsight"]["body"]) < 120:
        raise ValueError("daily insight lacks enough themes or analytical depth")
    if previous_insight:
        previous_text = f"{previous_insight.get('title', '')} {previous_insight.get('body', '')}"
        current_text = f"{data['dailyInsight']['title']} {data['dailyInsight']['body']}"
        similarity = SequenceMatcher(None, previous_text, current_text).ratio()
        if similarity > 0.82:
            raise ValueError(f"daily insight too similar to previous issue: {similarity:.2f}")
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"issue": issue, "stories": len(stories), "overlap": overlap, "categories": Counter(s["category"] for s in stories), "backup": str(backup)}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
