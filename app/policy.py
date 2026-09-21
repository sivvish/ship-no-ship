from __future__ import annotations

from app.models import Decision, GateHit, PullRequest, SignalSet, Verdict
from app.signals import extract


LARGE_FILES = 30
LARGE_LINES = 800


def _risk(verdict: Verdict, clause: str) -> str:
    if verdict == "Block":
        return (
            "If we Block, we might delay a safe change. "
            "If we had Shipped, we might land an unverified or unsafe one."
        )
    if verdict == "Changes":
        return (
            "If we hold for Changes, we might slow a small fix. "
            "If we Ship now, we might land work a human would split or test first."
        )
    return (
        "If we Ship, we might miss a defect the gates do not cover. "
        "If we Block, we would delay a change that already cleared the bar."
    )


def _to_ship(verdict: Verdict, hits: list[GateHit]) -> list[str]:
    if verdict == "Ship":
        return []
    items: list[str] = []
    for g in hits:
        if g.verdict == "Ship":
            continue
        if g.clause == "BLOCK_SECRETS":
            items.append("Remove secrets from the diff. Rotate anything that was committed.")
        elif g.clause == "BLOCK_CI_FAILED":
            items.append("Get a green check-run on the head SHA.")
        elif g.clause == "BLOCK_NO_CI_APP":
            items.append("Run CI on the application change, or drop the application files.")
        elif g.clause == "BLOCK_SENSITIVE_NO_TESTS":
            items.append("Add a test file that covers the sensitive path, or drop that path.")
        elif g.clause == "BLOCK_DESTRUCTIVE":
            items.append("Drop force-push, filter, submodule pointer, or secret-exfil workflow changes.")
        elif g.clause == "BLOCK_FALSE_VERIFICATION":
            items.append("Put the tests in the diff, or stop claiming they exist.")
        elif g.clause == "CHANGES_LOGIC_NO_TESTS":
            items.append("Add a test file for the logic, or shrink the change to docs/tests.")
        elif g.clause == "CHANGES_TOO_LARGE":
            items.append("Split under 30 files and 800 changed lines.")
        elif g.clause == "CHANGES_CHECKS_PENDING":
            items.append("Wait until checks finish green.")
        elif g.clause == "CHANGES_INTENT":
            items.append("Make the title and body describe the actual diff.")
        elif g.clause == "CHANGES_BLAST_RADIUS":
            items.append("State what the agent may touch, and what happens if it is wrong.")
    # unique
    out: list[str] = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


def apply_gates(signals: SignalSet) -> list[GateHit]:
    hits: list[GateHit] = []
    ci = signals.ci
    has_tests = bool(signals.test_files)
    app = signals.application_files
    docs_or_tests_only = signals.docs_only or signals.tests_only or not app

    if signals.secret_hits:
        hits.append(
            GateHit(
                clause="BLOCK_SECRETS",
                verdict="Block",
                detail="Credentials or secret paths in the diff.",
                source="deterministic",
                evidence="; ".join(signals.secret_hits[:6]),
            )
        )
        return hits

    if ci.get("any_failed"):
        hits.append(
            GateHit(
                clause="BLOCK_CI_FAILED",
                verdict="Block",
                detail="Head SHA has a failed check.",
                source="deterministic",
                evidence=", ".join(ci.get("failed") or []) or "combined-status",
            )
        )
        return hits

    if app and not ci.get("ran"):
        hits.append(
            GateHit(
                clause="BLOCK_NO_CI_APP",
                verdict="Block",
                detail="Application code changed and no checks ran on head.",
                source="deterministic",
                evidence=", ".join(app[:8]),
            )
        )
        return hits

    if signals.sensitive_files and not has_tests:
        hits.append(
            GateHit(
                clause="BLOCK_SENSITIVE_NO_TESTS",
                verdict="Block",
                detail="Sensitive path changed with no test file in the diff.",
                source="deterministic",
                evidence=", ".join(signals.sensitive_files[:8]),
            )
        )
        return hits

    if signals.destructive_hits:
        hits.append(
            GateHit(
                clause="BLOCK_DESTRUCTIVE",
                verdict="Block",
                detail="Destructive git or a workflow that can exfiltrate.",
                source="deterministic",
                evidence="; ".join(signals.destructive_hits[:6]),
            )
        )
        return hits

    if signals.claimed_tests_added and not has_tests:
        hits.append(
            GateHit(
                clause="BLOCK_FALSE_VERIFICATION",
                verdict="Block",
                detail="Title or body claims tests were added. No test file is in the diff.",
                source="deterministic",
                evidence="claimed tests added; test files: (none)",
            )
        )
        return hits

    if signals.claimed_tests_passed and not ci.get("green"):
        hits.append(
            GateHit(
                clause="BLOCK_FALSE_VERIFICATION",
                verdict="Block",
                detail="Title or body claims tests passed. Head is not green.",
                source="deterministic",
                evidence=f"ci green={ci.get('green')} ran={ci.get('ran')}",
            )
        )
        return hits

    # Changes
    if app and not has_tests:
        hits.append(
            GateHit(
                clause="CHANGES_LOGIC_NO_TESTS",
                verdict="Changes",
                detail="Application logic changed and no test file is in the diff.",
                source="deterministic",
                evidence=", ".join(app[:8]),
            )
        )
        return hits

    if signals.size["files"] >= LARGE_FILES or signals.size["changed_lines"] >= LARGE_LINES:
        hits.append(
            GateHit(
                clause="CHANGES_TOO_LARGE",
                verdict="Changes",
                detail=(
                    f"{signals.size['files']} files, "
                    f"{signals.size['changed_lines']} changed lines "
                    f"(bar is {LARGE_FILES} files or {LARGE_LINES} lines)."
                ),
                source="deterministic",
                evidence=f"files={signals.size['files']} lines={signals.size['changed_lines']}",
            )
        )
        return hits

    if ci.get("pending_only") or (ci.get("ran") and not ci.get("green") and not ci.get("any_failed")):
        if not docs_or_tests_only:
            hits.append(
                GateHit(
                    clause="CHANGES_CHECKS_PENDING",
                    verdict="Changes",
                    detail="Checks have not finished green.",
                    source="deterministic",
                    evidence=", ".join((ci.get("pending") or [])[:6]) or ci.get("combined"),
                )
            )
            return hits

    hits.append(
        GateHit(
            clause="SHIP",
            verdict="Ship",
            detail="No Block or Changes gate fired.",
            source="deterministic",
            evidence="checks green" if ci.get("green") else "docs/tests-only or no remaining gate",
        )
    )
    return hits


def decide_deterministic(pr: PullRequest) -> tuple[SignalSet, list[GateHit], Verdict, str]:
    signals = extract(pr)
    hits = apply_gates(signals)
    top = hits[0]
    return signals, hits, top.verdict, top.clause


def merge_llm(
    signals: SignalSet,
    hits: list[GateHit],
    llm: dict | None,
) -> Decision:
    top = hits[0]
    verdict: Verdict = top.verdict
    clause = top.clause
    detail = top.detail
    truncated = bool(llm and llm.get("truncated"))
    model = (llm or {}).get("model")

    if verdict != "Block" and llm and llm.get("ok"):
        suggested = llm.get("verdict")
        llm_clause = llm.get("clause")
        if suggested == "Changes" and verdict == "Ship":
            extra = GateHit(
                clause=llm_clause if llm_clause in {"CHANGES_INTENT", "CHANGES_BLAST_RADIUS"} else "CHANGES_INTENT",
                verdict="Changes",
                detail=llm.get("detail") or "Jev downgraded Ship to Changes.",
                source="jev",
                evidence=llm.get("evidence") or "",
            )
            hits = [extra] + hits
            verdict = "Changes"
            clause = extra.clause
            detail = extra.detail
        # LLM cannot Block, cannot upgrade Changes to Ship.

    if verdict == "Block":
        # drop any llm verdict influence
        pass

    return Decision(
        verdict=verdict,
        clause=clause,
        detail=detail,
        gates=hits,
        signals=signals,
        llm=llm,
        truncated=truncated,
        risk_line=_risk(verdict, clause),
        to_ship=_to_ship(verdict, hits),
        model=model,
    )
