from __future__ import annotations

import re
from dataclasses import dataclass


PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pulls?/(?P<number>\d+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PrRef:
    owner: str
    repo: str
    number: int

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"

    @property
    def key(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


def parse_pr_url(url: str) -> PrRef:
    raw = (url or "").strip()
    match = PR_URL_RE.match(raw)
    if not match:
        raise ValueError(
            "Need a public GitHub pull request URL like https://github.com/owner/repo/pull/123."
        )
    return PrRef(
        owner=match.group("owner"),
        repo=match.group("repo"),
        number=int(match.group("number")),
    )
