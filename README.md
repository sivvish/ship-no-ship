# Ship/no-ship

Paste a public GitHub pull request. Get **Ship**, **Changes**, or **Block**.

Code review bots comment. This decides. The decision is the product.

Repo: https://github.com/sivvish/ship-no-ship

There is no permanent public host yet. Local uvicorn is the way to run it.

## The problem

Agents open pull requests. Copilot review, CodeRabbit, Bugbot and Claude Code Review leave comments. Copilot never even requests changes, so it cannot be a required reviewer. Nobody publishes the bar for when that code may land.

This is that bar. It is not a 0–5 score. It is not the ServiceNow peer-review rubric. It is a merge policy for agent-written diffs.

## The bet

Deterministic gates first. Jev (TypeSafe System One) only on intent and blast radius, as typed nouls, and never to override a Block. If a chat model writes the verdict this is a wrapper.

## Policy

[POLICY.md](POLICY.md) is the source of truth. `/policy` renders it. Numbers that cannot drift:

- Large: 30 files or 800 changed lines.
- Failed CI is always a Block.
- Application code with no checks is a Block.
- Sensitive paths (auth, payments, migrations, prod infra, lockfiles and workflows) with no test file are a Block.

## Eval (holdout, n=10)

Labeled 40 public agent PRs by walking POLICY.md against the files, checks and body. 10 were frozen as holdout before looking at misses as a tuning signal. The published holdout run is deterministic (no Jev). Dated 2026-09-21. Jev is a live overlay on non-Block verdicts. Do not retune holdout against it.

| Metric | Value |
|---|---|
| Exact verdict match | 8 / 10 |
| Missed Block (gold Block, system not Block) | 0 / 5 |
| False Block (gold Ship, system Block) | 0 / 2 |

n=10 is directional. Two holdout misses are **over-Blocks**, not escaped defects:

- [tvninja#21](https://github.com/Giuig/tvninja/pull/21): body says they will *not* force-push `main`. The gate still fires on the words "force-push".
- [metamask-mobile#36477](https://github.com/MetaMask/metamask-mobile/pull/36477): "existing unit tests continue to pass" is not a claim that tests were added.

If those numbers were 10/10 I would not believe the set. `/examples` highlights the misses.

## What we refuse (v0)

- Style nits, naming, "consider a comment here."
- Auto-fix or push-a-commit.
- A score.
- Private repo OAuth.
- "Looks good to me" rubber stamps on failed CI.
- Line-level comments. (Explicit cut.)

## What would have to be true to become a GitHub App

Users who come back. A check-run on the PR. Earned autonomy after a class of change stays clean. That is a later project. Not this one.

## Run

`GITHUB_TOKEN` is required. `TYPESAFE_API_KEY` is optional. Without it, Jev is skipped and the deterministic verdict stands. That is the intended failure mode, not a crash.

```
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Stop with Ctrl+C. Do not leave uvicorn running after you are done. Do not leave a tunnel (loca.lt, ngrok, cloudflared) running either. A tunnel is an optional demo only and is not the product. Do not put a tunnel URL in this README.

```
python -m pytest
python -m eval.run
```

Public GitHub only. Do not point this at employer repos.

## Cut

Line-level comments. A hiring manager can get that from CodeRabbit. They cannot get a published merge bar from CodeRabbit.
