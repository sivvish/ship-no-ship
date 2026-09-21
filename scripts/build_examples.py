"""Write examples/index.json from gold + deterministic system verdicts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.github_client import fetch_pull  # noqa: E402
from app.parse import parse_pr_url  # noqa: E402
from app.policy import decide_deterministic  # noqa: E402


def main() -> None:
    gold = []
    for line in (ROOT / "eval" / "gold.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            gold.append(json.loads(line))
    # Prefer misses, then one of each clause.
    items = []
    for g in gold:
        pull = fetch_pull(parse_pr_url(g["html_url"]), use_cache=True)
        _, hits, verdict, clause = decide_deterministic(pull)
        items.append(
            {
                "id": g["key"].replace("/", "-").replace("#", "-"),
                "key": g["key"],
                "html_url": g["html_url"],
                "title": g["title"],
                "agent": g["agent"],
                "split": g["split"],
                "gold_verdict": g["gold_verdict"],
                "gold_clause": g["gold_clause"],
                "system_verdict": verdict,
                "system_clause": clause,
                "notes": g["notes"],
            }
        )
    misses = [i for i in items if i["gold_verdict"] != i["system_verdict"]]
    rest = [i for i in items if i["gold_verdict"] == i["system_verdict"]]
    # Gallery: all misses, then a spread of matches (max 10).
    gallery = misses[:6]
    seen_clause = {i["gold_clause"] for i in gallery}
    for i in rest:
        if len(gallery) >= 10:
            break
        if i["gold_clause"] in seen_clause and len(gallery) >= 6:
            continue
        gallery.append(i)
        seen_clause.add(i["gold_clause"])
    out = ROOT / "examples" / "index.json"
    out.write_text(json.dumps(gallery, indent=2), encoding="utf-8")
    print("gallery", len(gallery), "misses_in_gallery", sum(1 for g in gallery if g["gold_verdict"] != g["system_verdict"]))
    for g in gallery:
        flag = "MISS" if g["gold_verdict"] != g["system_verdict"] else "ok"
        print(flag, g["key"], g["gold_verdict"], "vs", g["system_verdict"])


if __name__ == "__main__":
    main()
