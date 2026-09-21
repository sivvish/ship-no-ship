from __future__ import annotations

import httpx

from app.judge import INTENT_SHIP_MIN, compose, judge
from app.policy import merge_llm
from tests.helpers import green, pr, py_file, red


def test_compose_never_returns_block():
    v, c = compose("Block", intent_noul=0.0, blast_noul=0.0, agent_detected=True)
    assert v == "Block"
    assert c is None


def test_compose_cannot_upgrade_changes():
    v, c = compose("Changes", intent_noul=0.99, blast_noul=0.99, agent_detected=True)
    assert v == "Changes"
    assert c is None


def test_compose_high_nouls_stay_ship():
    v, c = compose("Ship", intent_noul=0.9, blast_noul=0.9, agent_detected=True)
    assert v == "Ship"
    assert c == "SHIP"


def test_compose_low_intent_downgrades():
    v, c = compose("Ship", intent_noul=0.2, blast_noul=0.99, agent_detected=True)
    assert v == "Changes"
    assert c == "CHANGES_INTENT"


def test_compose_uncertain_intent_does_not_ship():
    v, c = compose("Ship", intent_noul=0.5, blast_noul=0.99, agent_detected=True)
    assert v == "Changes"
    assert c == "CHANGES_INTENT"
    assert 0.5 < INTENT_SHIP_MIN


def test_compose_low_blast_only_when_agent():
    v, c = compose("Ship", intent_noul=0.9, blast_noul=0.1, agent_detected=True)
    assert v == "Changes"
    assert c == "CHANGES_BLAST_RADIUS"
    v2, c2 = compose("Ship", intent_noul=0.9, blast_noul=0.1, agent_detected=False)
    assert v2 == "Ship"
    assert c2 == "SHIP"


def test_compose_intent_wins_when_both_low():
    v, c = compose("Ship", intent_noul=0.1, blast_noul=0.1, agent_detected=True)
    assert v == "Changes"
    assert c == "CHANGES_INTENT"


def test_judge_skips_on_deterministic_block():
    p = pr(files=[py_file("src/app.py")], check_runs=red())
    from app.policy import decide_deterministic

    signals, _, det, _ = decide_deterministic(p)
    assert det == "Block"

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Jev must not be called on Block")

    out = judge(p, signals, det, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["skipped"] is True
    assert "Block" in out["reason"]


def test_judge_skips_without_key(monkeypatch):
    # Empty must win over a real key in .env. delenv would let _load_env refill it.
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    p = pr(
        title="fix off-by-one",
        files=[py_file("src/util.py"), py_file("tests/test_util.py")],
        check_runs=green(),
    )
    from app.policy import decide_deterministic

    signals, _, det, _ = decide_deterministic(p)
    out = judge(p, signals, det)
    assert out["skipped"] is True
    assert "TYPESAFE_API_KEY" in out["reason"]


def test_judge_http_error_does_not_crash(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test")
    p = pr(
        title="fix off-by-one",
        files=[py_file("src/util.py"), py_file("tests/test_util.py")],
        check_runs=green(),
    )
    from app.policy import decide_deterministic

    signals, hits, det, _ = decide_deterministic(p)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "nope"})

    out = judge(p, signals, det, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["ok"] is False
    assert "401" in out["error"]
    decision = merge_llm(signals, hits, out)
    assert decision.verdict == "Ship"


def test_judge_downgrades_ship_on_low_intent(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test")
    p = pr(
        title="fix off-by-one",
        body="Generated with Claude Code",
        files=[py_file("src/util.py"), py_file("tests/test_util.py")],
        check_runs=green(),
        commit_messages=["fix\n\nGenerated with Claude Code"],
    )
    from app.policy import decide_deterministic

    signals, hits, det, _ = decide_deterministic(p)
    assert det == "Ship"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "intent_match": {"type": "noul", "noul": 0.12},
                    "blast_clear": {"type": "noul", "noul": 0.95},
                    "verification": {
                        "type": "choice",
                        "choice": "verified",
                        "confidence": 0.8,
                        "probabilities": {"verified": 0.8, "claimed": 0.1, "unclear": 0.1},
                    },
                },
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    out = judge(p, signals, det, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["ok"] is True
    assert out["verdict"] == "Changes"
    assert out["clause"] == "CHANGES_INTENT"
    decision = merge_llm(signals, hits, out)
    assert decision.verdict == "Changes"
    assert decision.clause == "CHANGES_INTENT"
    assert decision.gates[0].source == "jev"


def test_merge_still_cannot_upgrade_when_jev_loves_it():
    p = pr(title="helper", files=[py_file("src/util.py")], check_runs=green())
    from app.policy import decide_deterministic

    signals, hits, det, _ = decide_deterministic(p)
    assert det == "Changes"
    decision = merge_llm(
        signals,
        hits,
        {
            "ok": True,
            "verdict": "Ship",
            "clause": "SHIP",
            "detail": "clear",
            "evidence": "intent_match=0.99",
            "model": "jev-1.13.0",
        },
    )
    assert decision.verdict == "Changes"
