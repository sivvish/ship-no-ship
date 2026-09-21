from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from app.models import CheckRun, FileChange, PullRequest
from app.parse import PrRef


CACHE_DIR = Path(__file__).resolve().parent.parent / "eval" / "cache"
GITHUB_API = "https://api.github.com"


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _headers() -> dict[str, str]:
    _load_env()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    headers = {
        "User-Agent": "ship-no-ship-v0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class GithubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = name.replace("/", "_").replace("#", "_")
    return CACHE_DIR / f"{safe}.json"


def _get(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
    resp = client.get(url, params=params, timeout=30.0)
    if resp.status_code == 404:
        raise GithubError("GitHub returned 404. The pull request is missing or not public.", 404)
    if resp.status_code == 403:
        raise GithubError("GitHub returned 403. Rate limit or token scope.", 403)
    if resp.status_code >= 400:
        raise GithubError(f"GitHub returned {resp.status_code}.", resp.status_code)
    return resp


def _paginate_files(client: httpx.Client, owner: str, repo: str, number: int) -> list[dict]:
    files: list[dict] = []
    page = 1
    while True:
        resp = _get(
            client,
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/files",
            params={"per_page": 100, "page": page},
        )
        chunk = resp.json()
        files.extend(chunk)
        if len(chunk) < 100 or page >= 3:
            break
        page += 1
    return files


def fetch_pull(ref: PrRef, *, use_cache: bool = True) -> PullRequest:
    cache = _cache_path(ref.key)
    if use_cache and cache.exists():
        return pull_from_raw(json.loads(cache.read_text(encoding="utf-8")))

    with httpx.Client(headers=_headers()) as client:
        pr = _get(client, f"{GITHUB_API}/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}").json()
        files = _paginate_files(client, ref.owner, ref.repo, ref.number)
        sha = pr["head"]["sha"]
        checks = _get(
            client,
            f"{GITHUB_API}/repos/{ref.owner}/{ref.repo}/commits/{sha}/check-runs",
            params={"per_page": 100},
        ).json()
        status = _get(
            client,
            f"{GITHUB_API}/repos/{ref.owner}/{ref.repo}/commits/{sha}/status",
        ).json()
        commits = _get(
            client,
            f"{GITHUB_API}/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/commits",
            params={"per_page": 30},
        ).json()

    raw = {
        "pr": pr,
        "files": files,
        "check_runs": checks.get("check_runs", []),
        "combined_status": status,
        "commits": commits,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(raw), encoding="utf-8")
    return pull_from_raw(raw)


def pull_from_raw(raw: dict) -> PullRequest:
    pr = raw["pr"]
    owner = pr["base"]["repo"]["owner"]["login"]
    repo = pr["base"]["repo"]["name"]
    files = [
        FileChange(
            filename=f.get("filename") or "",
            status=f.get("status") or "modified",
            additions=int(f.get("additions") or 0),
            deletions=int(f.get("deletions") or 0),
            patch=f.get("patch"),
            previous_filename=f.get("previous_filename"),
        )
        for f in raw.get("files") or []
    ]
    check_runs = [
        CheckRun(
            name=c.get("name") or "check",
            status=c.get("status") or "",
            conclusion=c.get("conclusion"),
        )
        for c in raw.get("check_runs") or []
    ]
    combined = raw.get("combined_status") or {}
    commits = raw.get("commits") or []
    labels = []
    for lab in pr.get("labels") or []:
        if isinstance(lab, dict):
            labels.append(lab.get("name") or "")
        else:
            labels.append(str(lab))
    user = pr.get("user") or {}
    return PullRequest(
        owner=owner,
        repo=repo,
        number=int(pr["number"]),
        title=pr.get("title") or "",
        body=pr.get("body") or "",
        html_url=pr.get("html_url") or "",
        head_sha=(pr.get("head") or {}).get("sha") or "",
        user_login=user.get("login") or "",
        merged=bool(pr.get("merged")),
        state=pr.get("state") or "",
        files=files,
        check_runs=check_runs,
        combined_status=combined.get("state") or "pending",
        commit_messages=[c.get("commit", {}).get("message") or "" for c in commits],
        labels=labels,
    )
