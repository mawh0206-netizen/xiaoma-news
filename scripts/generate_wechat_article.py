"""Generate a WeChat-editor-friendly daily article from data/news.json."""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "news.json"
OUTPUT = ROOT / "runtime" / "wechat_article.html"
PAYLOAD = ROOT / "runtime" / "wechat_payload.json"
SITE = "https://mawh0206-netizen.github.io/xiaoma-news"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def detail_url(index: int) -> str:
    return f"{SITE}/detail.html?story={index}"


def story_block(story: dict, index: int, number: int) -> str:
    return f"""
    <section style="margin:0 0 28px;padding:0 0 25px;border-bottom:1px solid #e9e5dc;">
      <p style="margin:0 0 8px;color:#d94f36;font-size:13px;font-weight:700;letter-spacing:.06em;">{number:02d} · {esc(story['source'])} · {esc(story.get('publishedLabel', '今日'))}</p>
      <h3 style="margin:0 0 12px;color:#171a19;font-size:20px;line-height:1.5;font-weight:700;">{esc(story['title'])}</h3>
      <p style="margin:0 0 12px;color:#343936;font-size:16px;line-height:1.9;">{esc(story['summary'])}</p>
      <p style="margin:0 0 13px;padding:12px 15px;background:#f5f3ee;border-left:3px solid #1d6a55;color:#4e5551;font-size:14px;line-height:1.8;"><strong style="color:#1d6a55;">小马解读：</strong>{esc(story['whyItMatters'])}</p>
      <a href="{detail_url(index)}" style="color:#d94f36;font-size:14px;text-decoration:none;font-weight:700;">查看详细核心内容 →</a>
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


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    stories = data["stories"]
    top = [(i, s) for i, s in enumerate(stories) if s.get("isTop")][:8]
    markets = select(stories, {"投资市场"}, 4)
    autos = select(stories, {"汽车产业", "汽车金融"}, 4)
    economy = select(stories, {"财经", "房地产"}, 3)
    bilingual = [(i, s) for i, s in enumerate(stories) if s.get("originalSummary") and s.get("translatedSummary")][:2]

    body: list[str] = []
    body.append(f"""
      <header style="padding:34px 24px;background:#171a19;color:#fff;">
        <p style="margin:0 0 12px;color:#ef7059;font-size:13px;font-weight:700;letter-spacing:.14em;">小马看世界 · DAILY BRIEF</p>
        <h1 style="margin:0 0 14px;font-size:30px;line-height:1.3;">{esc(data['dateLabel'])} 新闻晨报</h1>
        <p style="margin:0;color:#c9ceca;font-size:15px;line-height:1.8;">为企业从业者与个人投资者筛选的科技、AI、资本市场和汽车行业信息。</p>
      </header>
      <section style="margin:0;padding:26px 24px;background:#f5f3ee;border-bottom:1px solid #ddd8cc;">
        <p style="margin:0 0 8px;color:#d94f36;font-size:13px;font-weight:700;">AI 今日判断</p>
        <h2 style="margin:0 0 12px;color:#171a19;font-size:23px;line-height:1.45;">{esc(data['dailyInsight']['title'])}</h2>
        <p style="margin:0;color:#454b47;font-size:15px;line-height:1.9;">{esc(data['dailyInsight']['body'])}</p>
      </section>""")

    body.append(section_title("01", "今日必读", "先看影响最大、传导范围最广的八条新闻"))
    body.extend(story_block(s, i, n) for n, (i, s) in enumerate(top, 1))
    body.append(section_title("02", "投资市场", "A股、港股、美股与关键资产价格"))
    body.extend(story_block(s, i, n) for n, (i, s) in enumerate(markets, 1))
    body.append(section_title("03", "汽车与汽车金融", "国内外整车、供应链、经销商与资金变化"))
    body.extend(story_block(s, i, n) for n, (i, s) in enumerate(autos, 1))
    body.append(section_title("04", "财经与房地产", "宏观政策、利率、企业融资与房地产市场"))
    body.extend(story_block(s, i, n) for n, (i, s) in enumerate(economy, 1))
    body.append(section_title("05", "英语学习 · 中英对照", "英文在前，中文逐句对应，不混入额外观点"))
    body.extend(bilingual_block(s, i) for i, s in bilingual)
    body.append(f"""
      <footer style="margin-top:42px;padding:28px 24px;background:#171a19;color:#d8dcd9;text-align:center;">
        <p style="margin:0 0 10px;color:#fff;font-size:20px;font-weight:700;">小马看世界</p>
        <p style="margin:0 0 15px;font-size:13px;line-height:1.7;">每日筛选 · 站内深度解读 · 国外新闻中英对照</p>
        <p style="margin:0 0 15px;"><a href="{SITE}/" style="color:#ef7059;font-size:14px;font-weight:700;text-decoration:none;">访问完整新闻网站 →</a></p>
        <p style="margin:0;color:#909792;font-size:11px;line-height:1.65;">本文为新闻信息整理与个人学习材料，不构成投资建议。新闻版权归原媒体所有。</p>
      </footer>""")

    article = "".join(body)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(data['dateLabel'])} · 小马看世界公众号稿</title>
<style>body{{margin:0;background:#ecebe7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}}.toolbar{{position:sticky;top:0;z-index:5;padding:12px;text-align:center;background:#fff;border-bottom:1px solid #ddd}}button{{padding:10px 18px;border:0;border-radius:4px;background:#1d6a55;color:#fff;font-size:14px;cursor:pointer}}#wechat-article{{width:min(677px,100%);margin:24px auto;background:#fff;box-shadow:0 10px 35px rgba(0,0,0,.08)}}@media(max-width:700px){{#wechat-article{{margin:0 auto}}}}</style></head>
<body><div class="toolbar"><button id="copyButton">复制公众号正文</button> <span id="copyStatus"></span></div>
<main id="wechat-article">{article}</main>
<script>document.getElementById('copyButton').onclick=async()=>{{const article=document.getElementById('wechat-article');try{{await navigator.clipboard.write([new ClipboardItem({{'text/html':new Blob([article.innerHTML],{{type:'text/html'}}),'text/plain':new Blob([article.innerText],{{type:'text/plain'}})}})]);document.getElementById('copyStatus').textContent='已复制，可粘贴到公众号编辑器';}}catch(e){{const range=document.createRange();range.selectNode(article);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);document.execCommand('copy');document.getElementById('copyStatus').textContent='已复制';}}}};</script></body></html>"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document, encoding="utf-8")
    payload = {
        "title": f"{data['dateLabel']}｜小马看世界新闻晨报",
        "author": "小马JLYYoung",
        "digest": data["dailyInsight"]["title"][:120],
        "content": article,
        "content_source_url": f"{SITE}/",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    PAYLOAD.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "payload": str(PAYLOAD), "top": len(top), "markets": len(markets), "autos": len(autos), "economy": len(economy), "bilingual": len(bilingual)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
