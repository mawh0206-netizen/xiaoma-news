import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
WECHAT = RUNTIME / "wechat_news.json"
MIN_WECHAT_STORIES = 11
PAYLOAD = RUNTIME / "wechat_payload.json"
DRAFT_RESULT = RUNTIME / "wechat_draft_result.json"
SUCCESS = RUNTIME / "daily_success.json"
READY = RUNTIME / "wechat_publish_ready.json"
CREDENTIALS = RUNTIME / "wechat_credentials.json"
CN_TZ = timezone(timedelta(hours=8))

sys.path.insert(0, str(ROOT / "scripts"))
import upload_wechat_draft as draft_api


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def canonical_stories(data: dict) -> list[dict]:
    keys = ("title", "source", "newsBrief", "whyItMatters", "watchMetrics", "url", "publishedAt")
    return [{key: story.get(key) for key in keys} for story in data.get("stories", [])]


def content_version(stories: list[dict]) -> str:
    raw = json.dumps(stories, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def online_issue(date_key: str) -> dict:
    stamp = int(datetime.now().timestamp() * 1000)
    url = f"https://mawh0206-netizen.github.io/xiaoma-news/data/wechat/{date_key}.json?v={stamp}"
    request = urllib.request.Request(url, headers={"User-Agent": "Xiaoma-News-Publish-Gate/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def find_drafts(token: str, title: str) -> list[dict]:
    found = []
    offset = 0
    while True:
        result = draft_api.json_request(
            "https://api.weixin.qq.com/cgi-bin/draft/batchget?"
            + urllib.parse.urlencode({"access_token": token}),
            {"offset": offset, "count": 20, "no_content": 0},
        )
        if result.get("errcode"):
            raise RuntimeError(f"微信草稿回读失败：{result.get('errcode')} {result.get('errmsg')}")
        items = result.get("item", [])
        for item in items:
            articles = (item.get("content") or {}).get("news_item") or []
            if articles and articles[0].get("title") == title:
                found.append({"media_id": item.get("media_id"), "article": articles[0]})
        offset += len(items)
        if not items or offset >= int(result.get("total_count", 0)):
            return found


def require_in_order(body: str, values: list[str], label: str) -> None:
    last = -1
    for index, value in enumerate(values, 1):
        position = body.find(value)
        if position < 0:
            raise ValueError(f"微信草稿缺少第{index}条{label}：{value[:40]}")
        if position <= last:
            raise ValueError(f"微信草稿{label}顺序与阅读原文不一致：第{index}条")
        last = position


def main() -> None:
    now = datetime.now(CN_TZ)
    date_key = now.strftime("%Y-%m-%d")
    local = read_json(WECHAT)
    payload = read_json(PAYLOAD)
    draft_result = read_json(DRAFT_RESULT)
    success = read_json(SUCCESS)

    if local.get("editorialReview", {}).get("status") != "passed":
        raise ValueError("公众号编辑复核尚未通过")
    if success.get("date") != date_key or success.get("status") != "success" or not success.get("before_09_00"):
        raise ValueError("当天生产成功标记未通过")

    local_stories = canonical_stories(local)
    if len(local_stories) < MIN_WECHAT_STORIES:
        raise ValueError(
            f"本地公众号少于{MIN_WECHAT_STORIES}条：{len(local_stories)}"
        )
    version = content_version(local_stories)

    online = online_issue(date_key)
    online_stories = canonical_stories(online)
    if online.get("editorialReview", {}).get("status") != "passed":
        raise ValueError("线上阅读原文编辑复核状态未通过")
    if online_stories != local_stories:
        raise ValueError("线上阅读原文与本地公众号内容或顺序不一致")

    token = draft_api.access_token(read_json(CREDENTIALS))
    drafts = find_drafts(token, payload["title"])
    if len(drafts) != 1:
        raise ValueError(f"微信当天同名草稿数量不是1：{len(drafts)}")
    draft = drafts[0]
    if draft.get("media_id") != draft_result.get("media_id"):
        raise ValueError("微信草稿media_id与本地记录不一致")

    article = draft["article"]
    body = html.unescape(article.get("content", ""))
    if article.get("content_source_url") != payload.get("content_source_url"):
        raise ValueError("微信草稿阅读原文链接与本地配置不一致")
    if "\ufffd" in body:
        raise ValueError("微信草稿正文包含乱码替换字符")
    if re.search(r"(?:今日|昨日)\s*\d{1,2}:\d{2}", body):
        raise ValueError("微信草稿正文仍包含逐条时间标签")

    require_in_order(body, [story["title"] for story in local_stories], "标题")
    require_in_order(body, [story["newsBrief"] for story in local_stories], "新闻事实")
    require_in_order(body, [story["whyItMatters"] for story in local_stories], "小马观察")
    for index, story in enumerate(local_stories, 1):
        for metric in story["watchMetrics"] or []:
            if metric not in body:
                raise ValueError(f"微信草稿缺少第{index}条跟踪指标：{metric}")

    state = {
        "date": date_key,
        "status": "ready",
        "verified_at": now.isoformat(),
        "content_version": version,
        "content_version_short": version[:12],
        "title": payload["title"],
        "lead_title": local_stories[0]["title"],
        "stories": len(local_stories),
        "draft_count": 1,
        "online_archive_match": True,
        "draft_full_text_match": True,
        "visible_time_labels": 0,
        "cover_sha256": draft_result.get("cover_sha256"),
        "email_sent": False,
    }
    if READY.exists():
        previous = read_json(READY)
        if previous.get("date") == date_key and previous.get("content_version") == version:
            state["email_sent"] = bool(previous.get("email_sent"))
            state["email_sent_at"] = previous.get("email_sent_at")
    READY.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
