"""Build the headline-only editorial review list without generating an issue."""
from __future__ import annotations

import json
from datetime import datetime

import prepare_daily_issue as daily
import prepare_wechat_issue as wechat


def main() -> None:
    payload = json.loads(wechat.CANDIDATES.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", payload)
    result = wechat.write_editorial_shortlist(candidates, datetime.now(daily.CN_TZ))
    print(
        "Editorial shortlist prepared: "
        f"{len(result['stories'])}/{result['eligibleAutomotiveHeadlines']} eligible headlines "
        f"from {result['inputCandidates']} inputs"
    )


if __name__ == "__main__":
    main()
