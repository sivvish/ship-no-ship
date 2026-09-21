from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Verdict = Literal["Ship", "Changes", "Block"]


@dataclass
class FileChange:
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str | None = None
    previous_filename: str | None = None


@dataclass
class CheckRun:
    name: str
    status: str
    conclusion: str | None


@dataclass
class PullRequest:
    owner: str
    repo: str
    number: int
    title: str
    body: str
    html_url: str
    head_sha: str
    user_login: str
    merged: bool
    state: str
    files: list[FileChange] = field(default_factory=list)
    check_runs: list[CheckRun] = field(default_factory=list)
    combined_status: str = "pending"
    commit_messages: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


@dataclass
class GateHit:
    clause: str
    verdict: Verdict
    detail: str
    source: str  # "deterministic" | "llm"
    evidence: str = ""


@dataclass
class SignalSet:
    agent: dict[str, Any]
    file_classes: dict[str, list[str]]
    secret_hits: list[str]
    test_files: list[str]
    application_files: list[str]
    sensitive_files: list[str]
    docs_only: bool
    tests_only: bool
    ci: dict[str, Any]
    size: dict[str, int]
    claimed_tests_added: bool
    claimed_tests_passed: bool
    destructive_hits: list[str]


@dataclass
class Decision:
    verdict: Verdict
    clause: str
    detail: str
    gates: list[GateHit]
    signals: SignalSet
    llm: dict[str, Any] | None
    truncated: bool
    risk_line: str
    to_ship: list[str]
    model: str | None = None
