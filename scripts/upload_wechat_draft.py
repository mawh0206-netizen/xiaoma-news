"""Upload the generated automotive briefing to WeChat's draft box.

Credentials and runtime results stay under runtime/, which is git-ignored.
This script never calls the publish or mass-send APIs.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
CREDENTIALS = RUNTIME / "wechat_credentials.json"
PAYLOAD = RUNTIME / "wechat_payload.json"
COVER = RUNTIME / "wechat_cover.png"
RESULT = RUNTIME / "wechat_draft_result.json"


def json_request(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read().decode("utf-8"))


def access_token(credentials: dict) -> str:
    result = json_request(
        "https://api.weixin.qq.com/cgi-bin/stable_token",
        {"grant_type": "client_credential", "appid": credentials["app_id"], "secret": credentials["app_secret"], "force_refresh": False},
    )
    if not result.get("access_token"):
        raise RuntimeError(f"token failed: {result.get('errcode')} {result.get('errmsg')}")
    return result["access_token"]


def upload_cover(token: str) -> str:
    boundary = "----XiaomaNews" + uuid.uuid4().hex
    filename = COVER.name
    mime = mimetypes.guess_type(filename)[0] or "image/png"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'.encode())
    body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
    body.extend(COVER.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    url = "https://api.weixin.qq.com/cgi-bin/material/add_material?" + urllib.parse.urlencode({"access_token": token, "type": "thumb"})
    request = urllib.request.Request(url, data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("media_id"):
        raise RuntimeError(f"cover upload failed: {result.get('errcode')} {result.get('errmsg')}")
    return result["media_id"]


def find_draft_media_id(token: str, title: str) -> str:
    result = json_request(
        "https://api.weixin.qq.com/cgi-bin/draft/batchget?" + urllib.parse.urlencode({"access_token": token}),
        {"offset": 0, "count": 20, "no_content": 0},
    )
    if result.get("errcode"):
        raise RuntimeError(f"draft lookup failed: {result.get('errcode')} {result.get('errmsg')}")
    for item in result.get("item", []):
        news_items = item.get("content", {}).get("news_item", [])
        if news_items and news_items[0].get("title") == title:
            return item.get("media_id", "")
    return ""


def add_draft(token: str, article: dict) -> str:
    result = json_request(
        "https://api.weixin.qq.com/cgi-bin/draft/add?" + urllib.parse.urlencode({"access_token": token}),
        {"articles": [article]},
    )
    if not result.get("media_id"):
        raise RuntimeError(f"draft creation failed: {result.get('errcode')} {result.get('errmsg')}")
    return result["media_id"]


def main() -> None:
    credentials = json.loads(CREDENTIALS.read_text(encoding="utf-8-sig"))
    article = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    token = access_token(credentials)
    existing = json.loads(RESULT.read_text(encoding="utf-8")) if RESULT.exists() else {}
    cover_sha256 = hashlib.sha256(COVER.read_bytes()).hexdigest()
    same_cover = (
        existing.get("title") == article.get("title")
        and existing.get("cover_sha256") == cover_sha256
        and existing.get("cover_media_id")
    )
    thumb_media_id = existing["cover_media_id"] if same_cover else upload_cover(token)
    article["thumb_media_id"] = thumb_media_id
    article["show_cover_pic"] = 1
    if existing.get("media_id") and existing.get("title") == article.get("title"):
        action = "updated"
        draft = json_request(
            "https://api.weixin.qq.com/cgi-bin/draft/update?" + urllib.parse.urlencode({"access_token": token}),
            {"media_id": existing["media_id"], "index": 0, "articles": article},
        )
        if draft.get("errcode") == 40007:
            recovered_media_id = find_draft_media_id(token, article["title"])
            if recovered_media_id:
                draft = json_request(
                    "https://api.weixin.qq.com/cgi-bin/draft/update?" + urllib.parse.urlencode({"access_token": token}),
                    {"media_id": recovered_media_id, "index": 0, "articles": article},
                )
                media_id = recovered_media_id
            else:
                media_id = add_draft(token, article)
                draft = {"errcode": 0}
                action = "created"
        else:
            media_id = existing["media_id"]
        if draft.get("errcode") != 0:
            raise RuntimeError(f"draft update failed: {draft.get('errcode')} {draft.get('errmsg')}")
    else:
        media_id, action = add_draft(token, article), "created"
    safe_result = {
        "media_id": media_id,
        "created_at": existing.get("created_at", int(time.time())),
        "updated_at": int(time.time()),
        "title": article["title"],
        "cover_media_id": thumb_media_id,
        "cover_sha256": cover_sha256,
    }
    RESULT.write_text(json.dumps(safe_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"action": action, "title": article["title"], "result": str(RESULT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
