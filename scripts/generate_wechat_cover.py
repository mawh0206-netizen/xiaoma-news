"""Render a data-driven daily WeChat cover image."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "runtime" / "wechat_news.json"
OUTPUT = ROOT / "runtime" / "wechat_cover.png"
WIDTH, HEIGHT = 1200, 511

PALETTES = [
    ("#101B23", "#1D6A55", "#E86A4A", "#F4EFE5"),
    ("#131A2A", "#315C8C", "#F0A44B", "#F6F1E8"),
    ("#211729", "#744A7D", "#E45D62", "#F5EFE7"),
    ("#17201C", "#3D725F", "#D9A441", "#F2EEE4"),
    ("#1E1A17", "#806147", "#D95B43", "#F5F0E8"),
]
MEDIA_BRANDS = (
    "汽车之家", "盖世汽车社区", "盖世汽车", "亿欧汽车", "亿欧",
    "财联社", "第一财经", "证券时报", "新出行", "Reuters",
    "Financial Times", "Electrek", "InsideEVs", "Automotive News", "TechCrunch",
)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["msyhbd.ttc", "msyh.ttc"] if bold else ["msyh.ttc", "msyhbd.ttc"]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def metric_values(story: dict) -> list[str]:
    text = f"{story.get('title', '')} {story.get('summary', '')}"
    values = re.findall(
        r"(?:约|超|近|达|增长|下降)?\s*\d+(?:\.\d+)?\s*"
        r"(?:%|万亿元|亿元|万美元|亿美元|万元|万辆|万台|万套|万|美元|元|辆|台|家|倍)",
        text,
        flags=re.I,
    )
    return list(dict.fromkeys(re.sub(r"\s+", "", value) for value in values))[:3]


def lead_score(story: dict) -> int:
    text = f"{story.get('title', '')} {story.get('summary', '')}".lower()
    score = len(metric_values(story)) * 8
    score += sum(
        weight
        for term, weight in {
            "销量": 10, "交付": 10, "产量": 8, "利润": 10, "召回": 10,
            "智能驾驶": 8, "车载ai": 8, "汽车金融": 7, "车贷": 8,
            "市场份额": 9, "渗透率": 8, "出口": 8, "库存": 8,
        }.items()
        if term in text
    )
    return score


def cover_title(story: dict) -> str:
    """Keep publisher attribution in the article, never in the visual cover."""
    title = str(story.get("title", "")).strip()
    title = re.sub(r"\s+[-—]\s+[^-—]{2,20}$", "", title).strip()
    for brand in MEDIA_BRANDS:
        title = title.replace(brand, "").strip(" -—｜|·")
    return re.sub(r"\s{2,}", " ", title)


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, max_width: int, lines: int) -> list[str]:
    if draw.textbbox((0, 0), text, font=face)[2] <= max_width:
        return [text]
    if lines == 2:
        candidates: list[tuple[int, int, str, str]] = []
        for split in range(2, len(text) - 1):
            left, right = text[:split], text[split:]
            left_width = draw.textbbox((0, 0), left, font=face)[2]
            right_width = draw.textbbox((0, 0), right, font=face)[2]
            if left_width <= max_width and right_width <= max_width:
                candidates.append((abs(left_width - right_width), -min(len(left), len(right)), left, right))
        if candidates:
            _, _, left, right = min(candidates)
            return [left, right]
    result: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textbbox((0, 0), candidate, font=face)[2] <= max_width:
            current = candidate
        else:
            result.append(current)
            current = char
            if len(result) == lines - 1:
                break
    consumed = sum(len(line) for line in result)
    if len(result) == lines - 1:
        remainder = text[consumed:]
        while remainder and draw.textbbox((0, 0), remainder + "…", font=face)[2] > max_width:
            remainder = remainder[:-1]
        result.append(remainder + ("…" if consumed + len(remainder) < len(text) else ""))
    elif current:
        result.append(current)
    return result[:lines]


def render_cover(data: dict, output: Path = OUTPUT) -> dict:
    stories = data["stories"]
    lead = max(stories, key=lead_score)
    headline = cover_title(lead)
    seed = hashlib.sha256(f"{data['dateLabel']}|{headline}".encode("utf-8")).digest()
    bg, accent, signal, paper = PALETTES[seed[0] % len(PALETTES)]
    image = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(image, "RGBA")

    for index in range(7):
        radius = 55 + seed[index + 1] % 150
        x = 820 + (seed[index + 8] % 430)
        y = -80 + (seed[index + 15] % 650)
        color = accent if index % 2 == 0 else signal
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=3)
    for index in range(6):
        y = 45 + index * 78 + seed[index + 20] % 24
        x1 = 760 + seed[index + 26] % 130
        x2 = WIDTH - 30
        draw.line((x1, y, x2, y - 80), fill=paper, width=2)

    draw.rectangle((0, 0, 24, HEIGHT), fill=signal)
    draw.text((70, 54), "小马儿YOUNG  ·  AUTOMOTIVE INTELLIGENCE", font=font(24, True), fill=signal)
    draw.text((70, 102), "汽车行业晨报", font=font(68, True), fill=paper)

    title_face = font(35, True)
    title_lines = wrap(draw, headline, title_face, 680, 2)
    title_y = 205
    for line in title_lines:
        draw.text((72, title_y), line, font=title_face, fill=paper)
        title_y += 54

    metrics = metric_values(lead)
    if metrics:
        chip_x = 72
        for value in metrics:
            box = draw.textbbox((0, 0), value, font=font(25, True))
            chip_width = box[2] - box[0] + 40
            draw.rounded_rectangle((chip_x, 338, chip_x + chip_width, 386), radius=10, fill=accent)
            draw.text((chip_x + 20, 346), value, font=font(25, True), fill=paper)
            chip_x += chip_width + 12

    date_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", data["dateLabel"])
    date_text = f"{date_match.group(1)}.{int(date_match.group(2)):02d}.{int(date_match.group(3)):02d}" if date_match else data["dateLabel"]
    draw.text((72, 438), date_text, font=font(25, True), fill=signal)
    draw.text((285, 438), "HEADLINE · INDUSTRY BRIEF", font=font(22), fill=paper)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"output": str(output), "sha256": digest, "lead": headline, "size": [WIDTH, HEIGHT]}


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    print(json.dumps(render_cover(data), ensure_ascii=False))


if __name__ == "__main__":
    main()
