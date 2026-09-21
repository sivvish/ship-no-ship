from __future__ import annotations

import json
import os
from pathlib import Path

from app.models import PullRequest, SignalSet, Verdict
from app.redact import redact


MODEL = "claude-sonnet-4-5"


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


def _policy_excerpt() -> str:
    path = Path(__file__).resolve().parent.parent / "POLICY.md"
    text = path.read_text(encoding="utf-8")
    # Keep the LLM clauses only, plus the hard rule.
    return (
        "You help apply a merge policy. Deterministic gates already ran.\n"
        "You may only return verdict Ship or Changes.\n"
        "You may never return Block.\n"
        "You may not upgrade Changes to Ship.\n"
        "Clauses you may fire: CHANGES_INTENT, CHANGES_BLAST_RADIUS.\n"
        "If intent matches and blast radius is clear, return Ship.\n\n"
        + text
    )


def _diff_excerpt(pr: PullRequest, limit_files: int = 20, limit_chars: int = 12000) -> tuple[str, bool]:
    scored: list[tuple[int, str, str]] = []
    for f in pr.files:
        name = f.filename.lower()
        score = 0
        if any(tok in name for tok in (".env", "auth", "secret", "workflow", "migrat", "stripe")):
            score += 5
        if "test" in name:
            score += 2
        score += min((f.additions or 0) + (f.deletions or 0), 50) / 50
        patch = redact(f.patch or "")
        scored.append((score, f.filename, patch))
    scored.sort(key=lambda x: x[0], reverse=True)
    truncated = len(pr.files) > limit_files
    chunks: list[str] = []
    used = 0
    for _, filename, patch in scored[:limit_files]:
        piece = f"FILE {filename}\n{patch}\n"
        if used + len(piece) > limit_chars:
            truncated = True
            break
        chunks.append(piece)
        used += len(piece)
    return "\n".join(chunks), truncated


def judge(
    pr: PullRequest,
    signals: SignalSet,
    deterministic_verdict: Verdict,
) -> dict:
    _load_env()
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if deterministic_verdict == "Block":
        return {"ok": False, "skipped": True, "reason": "deterministic Block; LLM not called"}
    if not key:
        return {"ok": False, "skipped": True, "reason": "ANTHROPIC_API_KEY missing; deterministic verdict stands"}

    excerpt, truncated = _diff_excerpt(pr)
    payload = {
        "title": pr.title,
        "body": redact(pr.body)[:4000],
        "agent": signals.agent,
        "deterministic_verdict": deterministic_verdict,
        "size": signals.size,
        "application_files": signals.application_files[:40],
        "test_files": signals.test_files[:40],
        "ci": {k: signals.ci[k] for k in ("ran", "green", "any_failed", "failed", "succeeded") if k in signals.ci},
        "diff_excerpt": excerpt,
    }
    instruction = (
        _policy_excerpt()
        + "\n\nReturn JSON only with keys:\n"
        + '{"verdict":"Ship"|"Changes","clause":"SHIP"|"CHANGES_INTENT"|"CHANGES_BLAST_RADIUS",'
        + '"detail":str,"evidence":str,"intent_match":bool,'
        + '"verified_or_claimed":"verified"|"claimed"|"unclear",'
        + '"blast_radius":str,"what_would_have_to_be_true":[str]}\n'
        + "If deterministic_verdict is Changes, you must return Changes.\n"
    )

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=key)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=800,
            messages=[
                {
                    "role": "user",
                    "content": instruction + "\n\nPR:\n" + json.dumps(payload)[:20000],
                }
            ],
        )
        text = "".join(part.text for part in msg.content if getattr(part, "type", "") == "text")
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            return {"ok": False, "error": "judge returned no JSON", "raw": text[:500], "truncated": truncated, "model": MODEL}
        data = json.loads(text[start : end + 1])
        verdict = data.get("verdict")
        if verdict not in {"Ship", "Changes"}:
            return {"ok": False, "error": "judge returned illegal verdict", "raw": data, "truncated": truncated, "model": MODEL}
        if deterministic_verdict == "Changes":
            verdict = "Changes"
        clause = data.get("clause") or ("CHANGES_INTENT" if verdict == "Changes" else "SHIP")
        return {
            "ok": True,
            "verdict": verdict,
            "clause": clause,
            "detail": data.get("detail") or "",
            "evidence": data.get("evidence") or "",
            "intent_match": data.get("intent_match"),
            "verified_or_claimed": data.get("verified_or_claimed"),
            "blast_radius": data.get("blast_radius") or "",
            "what_would_have_to_be_true": data.get("what_would_have_to_be_true") or [],
            "truncated": truncated,
            "model": MODEL,
        }
    except Exception as exc:  # noqa: BLE001 — surface judge failure, do not crash the verdict
        return {
            "ok": False,
            "error": str(exc)[:300],
            "truncated": truncated,
            "model": MODEL,
        }
