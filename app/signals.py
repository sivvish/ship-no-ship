from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.models import FileChange, PullRequest, SignalSet


FAILED_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}
SUCCESS_CONCLUSIONS = {"success"}

DOC_EXTS = {".md", ".rst", ".adoc", ".txt"}
DOC_NAMES = {
    "readme",
    "license",
    "licence",
    "changelog",
    "changes",
    "contributing",
    "authors",
    "code_of_conduct",
    "security",
    "notice",
    "copying",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}
LOCKFILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "cargo.lock",
    "go.sum",
    "uv.lock",
    "composer.lock",
    "gemfile.lock",
    "bun.lock",
    "bun.lockb",
}
ENV_OK = {".env.example", ".env.sample", ".env.template", ".env.test"}

AUTH_TOKENS = {"auth", "oauth", "saml", "jwt", "session", "passport", "sso"}
PAY_TOKENS = {"stripe", "payment", "payments", "billing", "checkout", "invoice"}
MIGRATE_TOKENS = {"migrations", "alembic"}
INFRA_NAMES = {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}
INFRA_TOKENS = {"terraform", "k8s", "kubernetes", "helm"}

SECRET_PATH_RE = re.compile(
    r"(?:^|/)(?:\.env(?:\.[A-Za-z0-9]+)?$|id_rsa$|[^/]+\.pem$|credentials\.json$|secrets\.(?:ya?ml|json)$)",
    re.I,
)

SECRET_LINE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("github_oauth", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{16,}")),
    (
        "aws_secret",
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*\S+"),
    ),
]

CLAIM_TESTS_ADDED = re.compile(
    r"(?i)(\b(added|adds|add|wrote|included|includes|with|via)\b.{0,40}\btests?\b)|(\btdd\b)|(\btest coverage\b)|(\bunit tests?\b)",
)
CLAIM_TESTS_PASSED = re.compile(
    r"(?i)(tests? (pass|passed|passing|are green)|all tests passed|ci is green|ci passed)",
)

AGENT_FOOTERS = [
    (re.compile(r"(?i)generated with claude code"), "claude-code"),
    (re.compile(r"(?i)co-authored-by:.*claude", re.I), "claude-code"),
    (re.compile(r"(?i)co-authored-by:.*cursor", re.I), "cursor"),
    (re.compile(r"(?i)made with cursor"), "cursor"),
    (re.compile(r"(?i)co-authored-by:.*copilot", re.I), "copilot"),
    (re.compile(r"(?i)openai.?codex|chatgpt.?codex|codex for github"), "codex"),
]
AGENT_LOGINS = {
    "copilot-swe-agent[bot]": "copilot",
    "copilot-swe-agent": "copilot",
    "chatgpt-codex-connector[bot]": "codex",
    "devin-ai-integration[bot]": "devin",
    "devin[bot]": "devin",
    "google-labs-jules[bot]": "jules",
}

FORCE_PUSH_RE = re.compile(r"(?i)(\bforce[- ]push\b|--force\b|git push\s+-f\b)")
FILTER_RE = re.compile(r"(?i)(git filter-branch|git-filter-repo)")
CURL_RE = re.compile(r"(?i)\b(curl|wget|invoke-webrequest)\b")
SECRETS_CTX_RE = re.compile(r"(?i)(secrets\.|\bSECRET\b)")


def _stem_tokens(filename: str) -> set[str]:
    path = PurePosixPath(filename.replace("\\", "/").lower())
    raw = set(path.parts)
    raw.add(path.stem.lower())
    bits: set[str] = set()
    for p in raw:
        bits.add(p)
        for bit in re.split(r"[._-]", p):
            if bit:
                bits.add(bit)
    return bits


def is_test_file(filename: str) -> bool:
    lower = filename.replace("\\", "/").lower()
    path = PurePosixPath(lower)
    parts = set(path.parts)
    if parts & {"test", "tests", "spec", "__tests__", "testdata"}:
        if "node_modules" not in parts:
            return True
    name = path.name
    if name.startswith("test_"):
        return True
    if name.endswith(("_test.py", "_test.go", "_test.ts", "_test.js", "_test.rb")):
        return True
    if name.endswith((".test.js", ".test.ts", ".test.tsx", ".test.jsx", ".spec.ts", ".spec.js", ".spec.tsx")):
        return True
    if name.endswith("test.java") or name.startswith("test") and name.endswith(".java"):
        return True
    return False


def is_docs_file(filename: str) -> bool:
    lower = filename.replace("\\", "/").lower()
    path = PurePosixPath(lower)
    if path.suffix in DOC_EXTS:
        return True
    if path.stem.lower() in DOC_NAMES:
        return True
    if "docs" in path.parts and path.suffix in DOC_EXTS | {".html", ""}:
        return True
    return False


def is_lockfile(filename: str) -> bool:
    return PurePosixPath(filename.replace("\\", "/")).name.lower() in LOCKFILE_NAMES


def is_image(filename: str) -> bool:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower() in IMAGE_EXTS


def is_env_ok(filename: str) -> bool:
    return PurePosixPath(filename.replace("\\", "/")).name.lower() in ENV_OK


def is_secret_path(filename: str) -> bool:
    lower = filename.replace("\\", "/")
    if is_env_ok(lower):
        return False
    return bool(SECRET_PATH_RE.search(lower))


def is_sensitive(filename: str) -> tuple[bool, str | None]:
    lower = filename.replace("\\", "/").lower()
    path = PurePosixPath(lower)
    tokens = _stem_tokens(lower)
    name = path.name.lower()

    if is_secret_path(filename):
        return True, "secrets-path"
    if is_lockfile(filename):
        return True, "lockfile"
    if name in INFRA_NAMES or name.startswith("docker-compose"):
        return True, "infra"
    if ".github" in path.parts and "workflows" in path.parts:
        return True, "workflow"
    if tokens & AUTH_TOKENS:
        return True, "auth"
    if tokens & PAY_TOKENS:
        return True, "payments"
    if tokens & MIGRATE_TOKENS:
        return True, "migrations"
    if tokens & INFRA_TOKENS:
        return True, "infra"
    if "terraform" in path.parts or path.suffix in {".tf", ".tfvars"}:
        return True, "infra"
    return False, None


def is_application_code(filename: str) -> bool:
    if is_docs_file(filename) or is_test_file(filename) or is_image(filename) or is_lockfile(filename):
        return False
    if is_env_ok(filename):
        return False
    if is_secret_path(filename):
        return True
    lower = filename.replace("\\", "/").lower()
    name = PurePosixPath(lower).name
    if name in {".gitignore", ".gitattributes", ".editorconfig", ".prettierrc", ".prettierignore"}:
        return False
    return True


def _agent(pr: PullRequest) -> dict:
    blob = "\n".join(
        [pr.title or "", pr.body or "", pr.user_login or ""] + list(pr.commit_messages or [])
    )
    labels = [a.lower() for a in (pr.labels or [])]
    login = (pr.user_login or "").lower()
    found: list[str] = []
    if login in AGENT_LOGINS:
        found.append(AGENT_LOGINS[login])
    for pat, name in AGENT_FOOTERS:
        if pat.search(blob):
            found.append(name)
    if "codex" in labels or login.startswith("codex"):
        found.append("codex")
    # de-dupe preserve order
    seen: list[str] = []
    for n in found:
        if n not in seen:
            seen.append(n)
    return {"detected": bool(seen), "names": seen, "login": pr.user_login}


def _ci(pr: PullRequest) -> dict:
    failed: list[str] = []
    succeeded: list[str] = []
    pending: list[str] = []
    for run in pr.check_runs or []:
        status = (run.status or "").lower()
        conclusion = (run.conclusion or "").lower() or None
        if status != "completed":
            pending.append(run.name)
            continue
        if conclusion in FAILED_CONCLUSIONS:
            failed.append(run.name)
        elif conclusion in SUCCESS_CONCLUSIONS:
            succeeded.append(run.name)
    combined = (pr.combined_status or "pending").lower()
    if combined in {"failure", "error"} and not failed:
        failed.append("combined-status")
    if combined == "success" and not succeeded and not failed:
        succeeded.append("combined-status")
    ran = bool(pr.check_runs) or combined in {"success", "failure", "error"}
    return {
        "ran": ran,
        "failed": failed,
        "succeeded": succeeded,
        "pending": pending,
        "combined": combined,
        "green": bool(succeeded) and not failed and not pending,
        "any_failed": bool(failed),
        "pending_only": bool(pending) and not failed and not succeeded,
    }


def _secret_hits(files: list[FileChange]) -> list[str]:
    hits: list[str] = []
    for f in files:
        if is_secret_path(f.filename):
            hits.append(f"path:{f.filename}")
        patch = f.patch or ""
        for label, pat in SECRET_LINE_PATTERNS:
            if pat.search(patch):
                hits.append(f"{label}:{f.filename}")
    # unique
    out: list[str] = []
    for h in hits:
        if h not in out:
            out.append(h)
    return out


def _destructive(pr: PullRequest, files: list[FileChange]) -> list[str]:
    hits: list[str] = []
    blob = "\n".join([pr.title or "", pr.body or ""] + list(pr.commit_messages or []))
    if FORCE_PUSH_RE.search(blob):
        hits.append("force-push-language")
    if FILTER_RE.search(blob):
        hits.append("git-filter")
    for f in files:
        lower = f.filename.replace("\\", "/").lower()
        patch = f.patch or ""
        if lower.endswith(".gitmodules") or "160000" in (patch[:200] if patch else ""):
            hits.append(f"submodule:{f.filename}")
        if FILTER_RE.search(patch):
            hits.append(f"git-filter:{f.filename}")
        if FORCE_PUSH_RE.search(patch):
            hits.append(f"force-push:{f.filename}")
        path = PurePosixPath(lower)
        if ".github" in path.parts and "workflows" in path.parts:
            if CURL_RE.search(patch) and SECRETS_CTX_RE.search(patch):
                hits.append(f"workflow-exfil:{f.filename}")
    out: list[str] = []
    for h in hits:
        if h not in out:
            out.append(h)
    return out


def extract(pr: PullRequest) -> SignalSet:
    files = pr.files or []
    test_files = [f.filename for f in files if is_test_file(f.filename)]
    application_files = [f.filename for f in files if is_application_code(f.filename)]
    docs_files = [f.filename for f in files if is_docs_file(f.filename)]
    sensitive: list[tuple[str, str]] = []
    classes: dict[str, list[str]] = {
        "auth": [],
        "payments": [],
        "migrations": [],
        "infra": [],
        "workflow": [],
        "lockfile": [],
        "secrets-path": [],
        "tests": test_files,
        "docs": docs_files,
        "application": application_files,
    }
    for f in files:
        hit, kind = is_sensitive(f.filename)
        if hit and kind:
            classes[kind].append(f.filename)
            sensitive.append((f.filename, kind))

    additions = sum(f.additions or 0 for f in files)
    deletions = sum(f.deletions or 0 for f in files)
    text = f"{pr.title or ''}\n{pr.body or ''}"

    docs_only = bool(files) and all(
        is_docs_file(f.filename) or is_image(f.filename) for f in files
    )
    tests_only = bool(files) and all(is_test_file(f.filename) or is_docs_file(f.filename) for f in files)

    return SignalSet(
        agent=_agent(pr),
        file_classes=classes,
        secret_hits=_secret_hits(files),
        test_files=test_files,
        application_files=application_files,
        sensitive_files=[f for f, _ in sensitive],
        docs_only=docs_only,
        tests_only=tests_only,
        ci=_ci(pr),
        size={
            "files": len(files),
            "additions": additions,
            "deletions": deletions,
            "changed_lines": additions + deletions,
        },
        claimed_tests_added=bool(CLAIM_TESTS_ADDED.search(text)),
        claimed_tests_passed=bool(CLAIM_TESTS_PASSED.search(text)),
        destructive_hits=_destructive(pr, files),
    )
