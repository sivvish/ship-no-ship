from __future__ import annotations

import re


_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{16,}"),
    re.compile(r"(?i)(aws_secret_access_key\s*[:=]\s*)\S+"),
]


def redact(text: str | None) -> str:
    if not text:
        return ""
    out = text
    for pat in _PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + "[redacted]", out)
        else:
            out = pat.sub("[redacted]", out)
    return out
