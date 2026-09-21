"""Fetch public agent PRs into eval/cache and write eval/candidates.json."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.github_client import GITHUB_API, GithubError, _headers, fetch_pull  # noqa: E402
from app.parse import PrRef  # noqa: E402
from app.policy import decide_deterministic  # noqa: E402
from app.signals import extract  # noqa: E402


QUERIES = [
    ('survived', 'is:pr "Generated with Claude Code" is:merged'),
    ('rejected', 'is:pr "Generated with Claude Code" is:closed is:unmerged'),
    ('failed-ci', 'is:pr "Generated with Claude Code" status:failure'),
    ('copilot-merged', 'is:pr author:copilot-swe-agent[bot] is:merged'),
    ('copilot-closed', 'is:pr author:copilot-swe-agent[bot] is:closed is:unmerged'),
    ('cursor', 'is:pr "Co-authored-by: Cursor" is:merged'),
    ('codex', 'is:pr "OpenAI Codex" is:pr is:merged'),
    ('workflows', 'is:pr "Generated with Claude Code" path:.github/workflows'),
    ('changes-requested', 'is:pr "Generated with Claude Code" review:changes-requested'),
    ('revert', 'is:pr revert "Generated with Claude Code" is:merged'),
]


def search(client: httpx.Client, q: str, per_page: int = 10) -> list[dict]:
    resp = client.get(
        f"{GITHUB_API}/search/issues",
        params={"q": q, "per_page": per_page, "sort": "updated"},
        timeout=30.0,
    )
    if resp.status_code != 200:
        print("search_fail", resp.status_code, q, resp.text[:200])
        return []
    return resp.json().get("items") or []


def main() -> None:
    seen: set[str] = set()
    rows: list[dict] = []
    with httpx.Client(headers=_headers()) as client:
        for bucket, q in QUERIES:
            print("search", bucket)
            items = search(client, q)
            time.sleep(2.2)  # search rate: 30/min
            for item in items:
                html = item.get("html_url") or ""
                if "/pull/" not in html:
                    continue
                parts = html.split("github.com/")[-1].split("/")
                if len(parts) < 4:
                    continue
                owner, repo, _, num = parts[0], parts[1], parts[2], parts[3]
                key = f"{owner}/{repo}#{num}"
                if key in seen:
                    continue
                seen.add(key)
                ref = PrRef(owner, repo, int(num))
                try:
                    pull = fetch_pull(ref, use_cache=True)
                except GithubError as exc:
                    print("skip", key, exc)
                    continue
                sig = extract(pull)
                _, hits, verdict, clause = decide_deterministic(pull)
                rows.append(
                    {
                        "key": key,
                        "html_url": pull.html_url,
                        "bucket_query": bucket,
                        "title": pull.title,
                        "user": pull.user_login,
                        "merged": pull.merged,
                        "state": pull.state,
                        "agent": sig.agent,
                        "files": [f.filename for f in pull.files[:40]],
                        "n_files": len(pull.files),
                        "changed_lines": sig.size["changed_lines"],
                        "application_files": sig.application_files[:20],
                        "test_files": sig.test_files[:20],
                        "sensitive_files": sig.sensitive_files[:20],
                        "secret_hits": sig.secret_hits[:10],
                        "destructive_hits": sig.destructive_hits[:10],
                        "claimed_tests_added": sig.claimed_tests_added,
                        "claimed_tests_passed": sig.claimed_tests_passed,
                        "ci": {
                            "ran": sig.ci["ran"],
                            "green": sig.ci["green"],
                            "any_failed": sig.ci["any_failed"],
                            "failed": sig.ci["failed"][:8],
                            "combined": sig.ci["combined"],
                        },
                        "docs_only": sig.docs_only,
                        "system_verdict": verdict,
                        "system_clause": clause,
                        "body_head": (pull.body or "")[:280],
                    }
                )
                print(f"  {key} {verdict}/{clause} files={len(pull.files)}")

    out = ROOT / "eval" / "candidates.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("wrote", out, "n=", len(rows))


if __name__ == "__main__":
    main()
