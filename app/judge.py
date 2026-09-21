from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from app.models import PullRequest, SignalSet, Verdict
from app.redact import redact


JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
# Stay Ship only when Jev is at least this sure. ~0.5 is "don't know" (TypeSafe noul).
# Uncertain must not Ship. Calibrate on the 30-dev set, never on holdout.
INTENT_SHIP_MIN = 0.6
BLAST_SHIP_MIN = 0.6


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


def _diff_excerpt(pr: PullRequest, limit_files: int = 20, limit_chars: int = 12000) -> tuple[str, bool]:
    scored: list[tuple[float, str, str]] = []
    for f in pr.files:
        name = f.filename.lower()
        score = 0.0
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


def compose(
    deterministic_verdict: Verdict,
    *,
    intent_noul: float | None,
    blast_noul: float | None,
    agent_detected: bool,
) -> tuple[Verdict, str | None]:
    """Map Jev nouls onto Ship/Changes. Never returns Block. Never upgrades Changes."""
    if deterministic_verdict == "Block":
        return "Block", None
    if deterministic_verdict == "Changes":
        return "Changes", None
    if intent_noul is None or intent_noul < INTENT_SHIP_MIN:
        return "Changes", "CHANGES_INTENT"
    if agent_detected and (blast_noul is None or blast_noul < BLAST_SHIP_MIN):
        return "Changes", "CHANGES_BLAST_RADIUS"
    return "Ship", "SHIP"


def _questions() -> dict[str, Any]:
    return {
        "intent_match": {
            "type": "noul",
            "instructions": (
                "Does `title` plus `body` describe the actual change in `diff_excerpt`? "
                "Yes if a reviewer would recognize the same work from the title. "
                "No if the title is generic, mismatched, or describes work that is not in the files."
            ),
            "criteria": {
                "true": "Title and body name the same change the diff makes.",
                "false": "Title/body are generic, wrong, or about something else.",
            },
        },
        "blast_clear": {
            "type": "noul",
            "instructions": (
                "Is it clear what this change is allowed to touch and what happens if it is wrong? "
                "Use `application_files`, `test_files`, `size` and `diff_excerpt`. "
                "Yes if the scope is bounded and reversible. "
                "No if mixed concerns, unclear blast radius, or sensitive paths without being called out."
            ),
            "criteria": {
                "true": "A reviewer can say which files matter and how to undo a bad merge.",
                "false": "Scope is fuzzy, mixed, or the failure mode is not obvious.",
            },
        },
        "verification": {
            "type": "choice",
            "instructions": (
                "Did this pull request actually verify the change, only claim verification, or is it unclear? "
                "Look at `test_files`, `ci` and `body`."
            ),
            "criteria": {
                "verified": "Tests or checks in the record actually cover the change.",
                "claimed": "The text claims tests or CI without matching files/checks.",
                "unclear": "Not enough to say.",
            },
        },
    }


def _state(pr: PullRequest, signals: SignalSet, excerpt: str, det: Verdict) -> dict[str, Any]:
    return {
        "title": pr.title,
        "body": redact(pr.body)[:4000],
        "agent_detected": bool(signals.agent.get("detected")),
        "agent_names": signals.agent.get("names") or [],
        "deterministic_verdict": det,
        "application_files": signals.application_files[:40],
        "test_files": signals.test_files[:40],
        "size": signals.size,
        "ci": {
            k: signals.ci[k]
            for k in ("ran", "green", "any_failed", "failed", "succeeded")
            if k in signals.ci
        },
        "diff_excerpt": excerpt,
    }


def _post_jev(state: dict[str, Any], client: httpx.Client, api_key: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "ship-no-ship-v0",
    }
    payload = {"model": JEV_MODEL, "state": state, "questions": _questions()}
    last_err = "jev request failed"
    for attempt in range(3):
        resp = client.post(JEV_URL, headers=headers, json=payload, timeout=30.0)
        if resp.status_code in {429, 529}:
            time.sleep(0.4 * (2**attempt))
            last_err = f"jev HTTP {resp.status_code}"
            continue
        if resp.status_code >= 400:
            # Do not include response body: it may echo state.
            raise RuntimeError(f"jev HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict) or "answers" not in data:
            raise RuntimeError("jev returned no answers")
        return data
    raise RuntimeError(last_err)


def _noul(answers: dict, name: str) -> float | None:
    item = answers.get(name) or {}
    if item.get("type") != "noul":
        return None
    try:
        return float(item["noul"])
    except (KeyError, TypeError, ValueError):
        return None


def judge(
    pr: PullRequest,
    signals: SignalSet,
    deterministic_verdict: Verdict,
    *,
    client: httpx.Client | None = None,
) -> dict:
    _load_env()
    key = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    excerpt, truncated = _diff_excerpt(pr)
    agent_detected = bool(signals.agent.get("detected"))

    if deterministic_verdict == "Block":
        return {
            "ok": False,
            "skipped": True,
            "reason": "deterministic Block; Jev not called",
            "truncated": truncated,
            "model": JEV_MODEL,
        }
    if not key:
        return {
            "ok": False,
            "skipped": True,
            "reason": "TYPESAFE_API_KEY missing; deterministic verdict stands",
            "truncated": truncated,
            "model": JEV_MODEL,
        }

    own_client = client is None
    http = client or httpx.Client()
    try:
        raw = _post_jev(
            _state(pr, signals, excerpt, deterministic_verdict),
            http,
            key,
        )
    except Exception as exc:  # noqa: BLE001 — judge failure must not crash the verdict
        return {
            "ok": False,
            "error": str(exc)[:200],
            "truncated": truncated,
            "model": JEV_MODEL,
        }
    finally:
        if own_client:
            http.close()

    answers = raw.get("answers") or {}
    intent = _noul(answers, "intent_match")
    blast = _noul(answers, "blast_clear")
    ver = answers.get("verification") or {}
    verdict, clause = compose(
        deterministic_verdict,
        intent_noul=intent,
        blast_noul=blast,
        agent_detected=agent_detected,
    )
    bits = [f"intent_match={intent if intent is not None else 'n/a'} (bar {INTENT_SHIP_MIN})"]
    bits.append(f"blast_clear={blast if blast is not None else 'n/a'} (bar {BLAST_SHIP_MIN})")
    if agent_detected:
        bits.append("agent detected")
    detail = {
        "CHANGES_INTENT": "Title/body do not clearly match the diff.",
        "CHANGES_BLAST_RADIUS": "Blast radius is unclear for an agent-written change.",
        "SHIP": "Jev cleared intent and blast radius.",
        None: "Deterministic Changes stands. Jev cannot upgrade it.",
    }[clause]
    return {
        "ok": True,
        "verdict": verdict,
        "clause": clause or "",
        "detail": detail,
        "evidence": "; ".join(bits),
        "intent_match": None if intent is None else intent >= INTENT_SHIP_MIN,
        "intent_noul": intent,
        "blast_noul": blast,
        "verified_or_claimed": ver.get("choice"),
        "verification": {
            "choice": ver.get("choice"),
            "confidence": ver.get("confidence"),
        },
        "blast_radius": f"blast_clear noul={blast}",
        "truncated": truncated,
        "model": raw.get("model") or JEV_MODEL,
        "usage": raw.get("usage") or {},
    }
