---
name: shoulder
description: Use during coding to calibrate reliance on human domain judgment, explanations, and evidence-based pushback using private repository knowledge levels.
---

Use this skill when asked to calibrate explanations, track repository understanding, or review learning evidence. Run `python3 <skill-directory>/scripts/shoulder.py init --repo /path/to/repo`, then `status` with the same repository. Requires Python 3.11+ and Git; the helper uses POSIX file locking.

Discover units from valid package.json, go.mod, pyproject.toml or Cargo.toml manifests under apps, services, packages and pkg. Otherwise use the root. Manifest paths provide discovery evidence. Unrated means unknown, never score 1. Reinitialization preserves ratings, including retired units; use only currently discovered units for calibration. Ask for an optional self-rating or brief explanation when the user wants to seed calibration.

Read the private ratings to adapt explanation depth and identify useful questions. A rating never grants authority or relaxes safeguards. Verify technical conclusions against the repository. Do not infer understanding from completed agent work, approval, requests, pasted reviews or outcomes. Ambiguous human authorship gives no learning credit. Keep inferred ratings provisional and explain their evidence and uncertainty. Self-ratings are authoritative and automatic reviews cannot overwrite or downgrade them. Inference never automatically downgrades an existing rating.

## Coding: human judgment and pushback

Consult the affected component's level, confidence and gaps before relying on human technical guidance. This is a signal of domain familiarity, not a probability that a claim is correct. A self-rating is authoritative about the recorded level, not about repository facts.

| Level | Reliance on human domain judgment | Pushback |
| --- | --- | --- |
| Unassessed or 1 | Establish context and investigate technical assumptions independently. | Explain concerns plainly with evidence; do not assume ignorance or error from an unknown level. |
| 2 | Use human input as a lead to verify; explain important assumptions. | Show the relevant flow and consequences when challenging a suggestion. |
| 3 | Use targeted human input on component behavior and tradeoffs. | Name the disputed assumption and compare it with the code or observed behavior. |
| 4 | Give substantial weight to demonstrated domain judgment within its proven scope. | Ask about missing context when evidence conflicts; state verified defects directly. |
| 5 | Treat the human as a domain expert within demonstrated scope. | Keep challenges concise and specific; still surface contradictions, risks and uncertainty. |

Low confidence or a known gap reduces reliance for that topic regardless of the headline level. Never agree merely because the level is high, and never challenge merely because it is low. Separate preferences from factual claims: respect authorized product choices while explaining verified technical consequences. When facts conflict, present the source and seek missing context instead of silently deferring or overriding the human. Explicit instructions and required authorization govern actions at every level.

Rubric:
1. Explicitly no knowledge.
2. Basic accurate component flow.
3. End-to-end understanding and a tradeoff.
4. Independent diagnosis, boundaries and failure modes.
5. Repeated architecture or operational reasoning, including uncommon failures.

Explicit calibration: `rate --repo /path/to/repo --unit apps/widget --score 3`. Only run this after the user supplies that self-rating. Do not convert agent-generated calibration into a self-rating.

Optional weekly review: first run `review --repo /path/to/repo --timezone Area/City --dry-run`. Inspect repository scope, timestamps and human-only evidence before an authorized actual `review`. The helper scans local Codex and Claude session JSONL. `--session-root` overrides those roots, repeatably. Scanning stops at 30 seconds or 1,500 files. Retain the newest 300 eligible messages across scanned roots within 120,000 text characters; omit messages over 12,000 characters. Coverage reports skipped records and truncation, so a bounded scan is not complete history. Git common-directory identity includes worktrees and excludes unrelated repositories even with equal names. Unknown session formats and unverifiable repository identity are excluded.

The latest completed review window is Monday 00:00 through Friday 17:00 in the chosen timezone, default UTC. A successful review runs once per week; three failed attempts stop that week's retries. Dry runs change no review counters. The evaluator runs Codex exec in the selected repository with read-only sandbox, ignored user configuration, low reasoning effort, and a configurable `--model` (default gpt-6.1-sol). It receives collected human messages, existing ratings and gaps, and unit names. It may verify technical claims with bounded read-only repository searches. It must omit unverified conclusions. Temporary evaluator output stays outside the repository. Reasons, gaps and assessment times persist. Existing Codex authentication is required. Evidence can contain sensitive text and the evaluator sends it to the configured model service; obtain authorization for that review scope. No user MCP configuration is changed or loaded.

Configure a Friday 17:00 schedule in the user's timezone only when scheduling is explicitly authorized, using the available scheduler. Test the manual command and dry run first. Schedule the same review command with absolute script and repository paths. Do not install a daemon or change OS scheduling implicitly. Scheduling backend and timezone handling depend on the user's environment.

State stays outside the checkout and installed skill at `~/.local/state/shoulder/<git-identity-sha256>/state.json`. `SHOULDER_STATE_DIR` overrides the state root. Never commit profiles, collected evidence or session history. Only source references, scores and review counters persist; dry-run output includes message text, so handle it privately. Do not copy private profiles into public skill files.
