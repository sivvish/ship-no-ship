from __future__ import annotations

from app.models import CheckRun, FileChange, PullRequest


def pr(
    *,
    title: str = "Fix login",
    body: str = "",
    files: list[FileChange] | None = None,
    check_runs: list[CheckRun] | None = None,
    combined_status: str = "success",
    user_login: str = "copilot-swe-agent[bot]",
    commit_messages: list[str] | None = None,
) -> PullRequest:
    return PullRequest(
        owner="acme",
        repo="app",
        number=1,
        title=title,
        body=body,
        html_url="https://github.com/acme/app/pull/1",
        head_sha="abc123",
        user_login=user_login,
        merged=False,
        state="open",
        files=files or [],
        check_runs=check_runs or [],
        combined_status=combined_status,
        commit_messages=commit_messages or [title],
        labels=[],
    )


def py_file(name: str, patch: str = "+print(1)\n", additions: int = 10, deletions: int = 0) -> FileChange:
    return FileChange(filename=name, status="modified", additions=additions, deletions=deletions, patch=patch)


def green() -> list[CheckRun]:
    return [CheckRun(name="tests", status="completed", conclusion="success")]


def red() -> list[CheckRun]:
    return [CheckRun(name="tests", status="completed", conclusion="failure")]
