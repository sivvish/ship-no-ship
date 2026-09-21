from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.github_client import fetch_pull  # noqa: E402
from app.parse import parse_pr_url  # noqa: E402
from app.policy import decide_deterministic, merge_llm  # noqa: E402
from app.judge import judge  # noqa: E402


GOLD = ROOT / "eval" / "gold.jsonl"
HOLDOUT = ROOT / "eval" / "holdout_ids.txt"
LAST = ROOT / "eval" / "last.json"


def load_gold() -> list[dict]:
    rows = []
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> None:
    holdout = set()
    if HOLDOUT.exists():
        holdout = {ln.strip() for ln in HOLDOUT.read_text(encoding="utf-8").splitlines() if ln.strip()}
    gold = load_gold()
    rows = []
    llm_used = False
    for g in gold:
        if holdout and g["key"] not in holdout:
            continue
        pull = fetch_pull(parse_pr_url(g["html_url"]), use_cache=True)
        signals, hits, det, _ = decide_deterministic(pull)
        llm = {"ok": False, "skipped": True, "reason": "eval run is deterministic-only"}
        # Holdout must not be used to tune the LLM. Keep eval deterministic.
        decision = merge_llm(signals, hits, llm)
        match = decision.verdict == g["gold_verdict"]
        rows.append(
            {
                "key": g["key"],
                "html_url": g["html_url"],
                "gold_verdict": g["gold_verdict"],
                "gold_clause": g["gold_clause"],
                "system_verdict": decision.verdict,
                "system_clause": decision.clause,
                "match": match,
                "split": g.get("split"),
            }
        )
        if llm.get("ok"):
            llm_used = True

    n = len(rows)
    exact = sum(1 for r in rows if r["match"])
    gold_block = [r for r in rows if r["gold_verdict"] == "Block"]
    gold_ship = [r for r in rows if r["gold_verdict"] == "Ship"]
    missed_block = sum(1 for r in gold_block if r["system_verdict"] != "Block")
    false_block = sum(1 for r in gold_ship if r["system_verdict"] == "Block")
    data = {
        "n": n,
        "exact_match": exact,
        "exact_match_pct": f"{(100 * exact / n):.0f}%" if n else "n/a",
        "gold_block_n": len(gold_block),
        "missed_block": missed_block,
        "gold_ship_n": len(gold_ship),
        "false_block": false_block,
        "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "llm_used": llm_used,
        "rows": rows,
    }
    LAST.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({k: data[k] for k in data if k != "rows"}, indent=2))
    for r in rows:
        flag = "OK" if r["match"] else "MISS"
        print(f"{flag} {r['key']} gold={r['gold_verdict']}/{r['gold_clause']} sys={r['system_verdict']}/{r['system_clause']}")


if __name__ == "__main__":
    main()
