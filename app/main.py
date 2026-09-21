from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.github_client import GithubError, fetch_pull
from app.judge import judge
from app.parse import parse_pr_url
from app.policy import decide_deterministic, merge_llm
from app.redact import redact


ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "eval" / "runs"
EXAMPLES = ROOT / "examples"
POLICY_MD = ROOT / "POLICY.md"
GOLD = ROOT / "eval" / "gold.jsonl"
HOLDOUT = ROOT / "eval" / "holdout_ids.txt"
LAST_EVAL = ROOT / "eval" / "last.json"

app = FastAPI(title="Ship/no-ship")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def _policy_html() -> str:
    text = POLICY_MD.read_text(encoding="utf-8")
    # Tiny markdown: headings, lists, code, hr. Enough for POLICY.md.
    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    for line in lines:
        if line.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(line.replace("&", "&amp;").replace("<", "&lt;") + "\n")
            continue
        if line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.strip() == "---":
            out.append("<hr>")
        elif line.startswith("- "):
            out.append(f"<li>{_inline(line[2:])}</li>")
        elif line.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    html = "\n".join(out)
    # wrap consecutive <li>
    while "<li>" in html:
        html = html.replace("<li>", "<ul><li>", 1)
        break
    return html


def _inline(text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # **bold**
    import re

    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _html(request: Request, name: str, context: dict, status_code: int = 200):
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def _save_run(run_id: str, payload: dict) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _decision_view(decision, pr, run_id: str) -> dict:
    signals = decision.signals
    rows = []
    for g in decision.gates:
        rows.append(
            {
                "clause": g.clause,
                "verdict": g.verdict,
                "detail": g.detail,
                "source": g.source,
                "evidence": redact(g.evidence),
            }
        )
    return {
        "run_id": run_id,
        "verdict": decision.verdict,
        "clause": decision.clause,
        "detail": decision.detail,
        "risk_line": decision.risk_line,
        "to_ship": decision.to_ship,
        "rows": rows,
        "agent": signals.agent,
        "ci": signals.ci,
        "size": signals.size,
        "truncated": decision.truncated,
        "model": decision.model,
        "llm": decision.llm,
        "pr": {
            "title": pr.title,
            "html_url": pr.html_url,
            "key": pr.key,
            "user": pr.user_login,
        },
        "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    examples = []
    index = EXAMPLES / "index.json"
    if index.exists():
        examples = json.loads(index.read_text(encoding="utf-8"))[:3]
    return _html(request, "home.html", {"examples": examples, "error": None})


@app.post("/review", response_class=HTMLResponse)
def review(request: Request, url: str = Form(...)):
    try:
        ref = parse_pr_url(url)
    except ValueError as exc:
        examples = []
        index = EXAMPLES / "index.json"
        if index.exists():
            examples = json.loads(index.read_text(encoding="utf-8"))[:3]
        return _html(request, "home.html", {"examples": examples, "error": str(exc)}, 400)
    try:
        pull = fetch_pull(ref, use_cache=True)
    except GithubError as exc:
        examples = []
        index = EXAMPLES / "index.json"
        if index.exists():
            examples = json.loads(index.read_text(encoding="utf-8"))[:3]
        extra = ""
        if exc.status == 404:
            extra = " Paste a public URL. Private repos are out of scope for v0."
        return _html(
            request,
            "home.html",
            {"examples": examples, "error": str(exc) + extra},
            400,
        )

    signals, hits, det_verdict, _ = decide_deterministic(pull)
    llm = judge(pull, signals, det_verdict)
    decision = merge_llm(signals, hits, llm)
    run_id = uuid.uuid4().hex[:12]
    view = _decision_view(decision, pull, run_id)
    _save_run(
        run_id,
        {
            "view": view,
            "gold_key": pull.key,
            "url": pull.html_url,
        },
    )
    return RedirectResponse(url=f"/r/{run_id}", status_code=303)


@app.get("/r/{run_id}", response_class=HTMLResponse)
def show_run(request: Request, run_id: str):
    path = RUNS / f"{run_id}.json"
    if not path.exists():
        return _html(request, "home.html", {"examples": [], "error": "Unknown review id."}, 404)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _html(request, "verdict.html", {"d": payload["view"]})


@app.get("/policy", response_class=HTMLResponse)
def policy_page(request: Request):
    text = POLICY_MD.read_text(encoding="utf-8")
    return _html(request, "policy.html", {"policy": text})


@app.get("/examples", response_class=HTMLResponse)
def examples_page(request: Request):
    index = EXAMPLES / "index.json"
    items = json.loads(index.read_text(encoding="utf-8")) if index.exists() else []
    return _html(request, "examples.html", {"items": items})


@app.get("/eval", response_class=HTMLResponse)
def eval_page(request: Request):
    data = None
    if LAST_EVAL.exists():
        data = json.loads(LAST_EVAL.read_text(encoding="utf-8"))
    return _html(request, "eval.html", {"data": data})


@app.get("/health")
def health():
    return {"ok": True}
