"""Resolve Google News RSS article wrappers to publisher URLs."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "runtime" / "google_news_url_cache.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je"


def is_google_news_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.hostname == "news.google.com" and "/articles/" in parsed.path


def article_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    value = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not value:
        raise ValueError(f"missing Google News article id: {url}")
    return value


def fetch_decoding_params(url: str) -> dict:
    identifier = article_id(url)
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8", "replace")
    signature = re.search(r'data-n-a-sg="([^"]+)"', page)
    timestamp = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not signature or not timestamp:
        raise ValueError(f"Google News decoding attributes missing: {identifier[:16]}")
    return {
        "url": url,
        "id": identifier,
        "signature": signature.group(1),
        "timestamp": int(timestamp.group(1)),
    }


def decode_batch(params: list[dict]) -> dict[str, str]:
    requests = []
    for item in params:
        payload = [
            "garturlreq",
            [
                ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
            ],
            item["id"],
            item["timestamp"],
            item["signature"],
        ]
        requests.append(["Fbv4je", json.dumps(payload, separators=(",", ":")), None, "generic"])
    body = urllib.parse.urlencode({"f.req": json.dumps([requests], separators=(",", ":"))}).encode()
    request = urllib.request.Request(
        BATCH_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": UA,
            "Referer": "https://news.google.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        text = response.read().decode("utf-8", "replace")
    sections = [part for part in text.split("\n\n") if part.lstrip().startswith("[")]
    if not sections:
        raise ValueError("Google News decoder returned no JSON section")
    outer = json.loads(sections[0])
    decoded = [json.loads(item[2])[1] for item in outer if item and item[0] == "wrb.fr" and item[1] == "Fbv4je"]
    if len(decoded) != len(params):
        raise ValueError(f"Google News decoder result mismatch: {len(decoded)}/{len(params)}")
    result = {}
    for item, url in zip(params, decoded):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.hostname == "news.google.com":
            raise ValueError(f"invalid decoded publisher URL: {url}")
        result[item["url"]] = url
    return result


def read_cache() -> dict[str, str]:
    try:
        payload = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        if payload.get("version") != 2 or not isinstance(payload.get("urls"), dict):
            return {}
        return payload["urls"]
    except Exception:
        return {}


def write_cache(cache: dict[str, str]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 2, "urls": cache}
    CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_one(url: str, attempts: int) -> str:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            params = fetch_decoding_params(url)
            return decode_batch([params])[url]
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Google News URL resolution failed for {article_id(url)[:16]}: {last_error}")


def resolve_urls(urls: list[str], attempts: int = 3) -> dict[str, str]:
    unique = list(dict.fromkeys(urls))
    cache = read_cache()
    result = {url: url for url in unique if not is_google_news_url(url)}
    pending = [url for url in unique if is_google_news_url(url) and cache.get(url)]
    result.update({url: cache[url] for url in pending})
    unresolved = [url for url in unique if is_google_news_url(url) and url not in result]
    if not unresolved:
        return result

    decoded: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(5, len(unresolved))) as executor:
        futures = {executor.submit(resolve_one, url, attempts): url for url in unresolved}
        for future in as_completed(futures):
            url = futures[future]
            decoded[url] = future.result()
    result.update(decoded)
    cache.update(decoded)
    write_cache(cache)
    return result
