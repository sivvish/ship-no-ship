# Ship/no-ship policy

Source of truth. The code in `app/policy.py` implements these gates. `/policy` renders this file. If the page and the code disagree, the code is wrong.

This is a merge decision for **agent-written pull requests**. It is not a review bot. It does not score. First matching **Block** wins. Then **Changes**. Else **Ship**.

Thresholds that are numbers, so they cannot drift:

- Large diff: **30 files** or **800 changed lines** (additions + deletions).
- “No checks” means zero completed check-runs and no combined-status success/failure on the head SHA.
- Failed checks: any check-run conclusion of `failure`, `timed_out`, or `startup_failure`, or combined status `failure`/`error`.

---

## Block

Any one is enough. The LLM cannot override a Block.

### `BLOCK_SECRETS`

Credentials or secrets in the diff.

- Path looks like a secret store: `.env` (not `.env.example` / `.env.sample` / `.env.template`), `id_rsa`, `*.pem`, `credentials.json`, `secrets.yml` / `secrets.yaml` / `secrets.json`.
- Patch contains a private key block, AWS access key (`AKIA…`), GitHub token (`ghp_` / `gho_` / `github_pat_`), Anthropic `sk-ant-`, or `aws_secret_access_key` assigned a value.

Displayed patches are redacted. A hit still Blocks.

### `BLOCK_CI_FAILED`

Head SHA has a failed check (see above). Failed CI is a Block even on docs. Do not rubber-stamp a red build.

### `BLOCK_NO_CI_APP`

The diff includes **application code** and **no checks ran**.

Application code is any changed file that is not documentation, license/changelog chrome, or a test file. Images and lockfiles are not application code for this clause (lockfiles have their own clause).

Docs/tests-only PRs with no CI are allowed to continue. Application code with no CI is not.

### `BLOCK_SENSITIVE_NO_TESTS`

The diff touches at least one **sensitive path** and **no test file** is in the diff.

Sensitive paths:

- Auth: path contains `auth`, `oauth`, `saml`, `jwt`, `session`, `passport`, or `sso` as a segment or filename stem.
- Payments: `stripe`, `payment`, `billing`, `checkout`, `invoice`.
- Migrations: `migrations`, `alembic`.
- Production infra: `Dockerfile`, `docker-compose`, `terraform`, `k8s` / `kubernetes` / `helm`, `.github/workflows`.
- Dependency lockfiles: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `Cargo.lock`, `go.sum`, `uv.lock`, `composer.lock`, `Gemfile.lock`, `bun.lock`.

### `BLOCK_DESTRUCTIVE`

Destructive git or a workflow that can exfiltrate.

- Submodule pointer (gitlink / `.gitmodules` change that looks like a pointer swap).
- Workflow file changed and the patch talks to the network (`curl`, `wget`, `invoke-webrequest`) **and** GitHub `secrets.` or `SECRET`.
- Patch or body talks about `git filter-branch`, `git-filter-repo`, or force-push (`--force`, `force push`, `force-push`).

### `BLOCK_FALSE_VERIFICATION`

The title or body **claims** tests were added or run, and the files/checks do not show that.

- Claim of adding tests (`added tests`, `with tests`, `TDD`, `test coverage`) requires a test file in the diff.
- Claim that tests passed or ran (`tests pass`, `all tests passed`, `CI is green`) requires a green check-run on head.

This is the “agent lied about verification” gate.

---

## Changes

Reached only if no Block fired.

### `CHANGES_LOGIC_NO_TESTS`

Application logic changed and no test file is in the diff, but the path is not in the Block-sensitive list (otherwise it would already have Blocked).

### `CHANGES_TOO_LARGE`

30 or more files, or 800 or more changed lines. A human would split this.

### `CHANGES_CHECKS_PENDING`

Checks exist but none have failed and none have completed successfully yet. Do not Ship on a yellow build.

### `CHANGES_INTENT` (LLM only)

Title/body intent does not match the diff. Deterministic code never fires this. The LLM may **downgrade Ship to Changes**. It may not Block. It may not upgrade Changes to Ship.

### `CHANGES_BLAST_RADIUS` (LLM only)

Agent attribution is present and blast radius is unclear. Same LLM limits as `CHANGES_INTENT`.

---

## Ship

### `SHIP`

No Block or Changes gate fired.

- Checks on head are green, **or** the diff is docs/comments/tests-only.
- Intent matches the diff (or the LLM was skipped / failed, in which case the deterministic verdict stands).

---

## What the LLM is allowed to do

One structured call, and only if the deterministic verdict is not Block:

1. Intent vs diff, with evidence quotes.
2. Did the agent actually verify, or only claim it?
3. Blast radius, and what would have to be true to ship.

It may not invent a fourth verdict. It may not override a deterministic Block. It may not override a deterministic Changes to Ship. If JSON fails, show the deterministic verdict and say the judge failed.

---

## What we refuse to add (v0)

- Style nits, naming, “consider a comment here.”
- Auto-fix or push-a-commit.
- A score.
- Private repo OAuth.
- “Looks good to me” rubber stamps on failed CI.
- Line-level comments. (Explicit cut.)

---

## What this is not

Not CodeRabbit. Not a 0–5 quality score. Not the ServiceNow peer-review rubric. Public GitHub pull requests only.
