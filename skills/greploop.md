---
name: greploop
description: Iterate a pull request until the automated reviewer (Greptile) gives 5/5 confidence with zero unresolved comments. Trigger review, fix actionable comments, push, re-review, repeat. Use to fully optimize a PR against the review bar. A narrow, PR-focused version of /goal.
triggers:
  - greploop
  - optimize the pull request
  - iterate the pull request
  - greptile review
  - perfect review score
---

# Greploop

> Adapted from greptileai/skills (MIT). Requires `gh` + Greptile installed on the repo. GitHub-first.

## The One Rule

**Loop to a hard bar, with a hard cap.** Exit only when the score is **5/5 AND
zero unresolved comments** — or **5 iterations**, whichever comes first. No
runaway loops, no "good enough" early stop.

## The Loop (max 5 iterations)

```
A. Trigger   push latest → if Greptile not already running, comment "@greptile review"
B. Wait      poll the Greptile check-run until status=completed
C. Fetch     parse score (N/5) + unresolved comments from the latest review
D. Decide    5/5 & 0 unresolved → DONE | else fix actionable items
E. Fix       implement each actionable comment (skills/implementer.md)
F. Repeat    back to A
```

## A — Trigger (only if not already running)

```bash
STATE=$(gh pr checks <N> --json name,state | jq -r '.[]|select(.name|test("greptile";"i")).state')
[ "$STATE" != "PENDING" ] && [ "$STATE" != "IN_PROGRESS" ] && gh pr comment <N> --body "@greptile review"
```

## B — Wait for the check

```bash
HEAD=$(gh pr view <N> --json headRefOid -q .headRefOid)
# poll repos/{owner}/{repo}/commits/$HEAD/check-runs for the greptile run until status=completed
```

## C — Fetch score + comments

Greptile may surface the score in the PR body, an **edited** general comment, or
a review. Read all three; trust the one with the latest `updated_at`.

```bash
gh api --paginate "repos/{owner}/{repo}/issues/<N>/comments?per_page=100"   # general (edited in place)
gh api repos/{owner}/{repo}/pulls/<N>/reviews                              # reviews
gh api repos/{owner}/{repo}/pulls/<N>/comments                             # unresolved inline
```

Parse for `N/5` (e.g. `Confidence: 3/5`) and carry forward the "Prompt to fix all
with AI" items even when inline comments are empty.

## D — Exit conditions (stop the loop)

```
DONE   score == 5/5 AND unresolved comments == 0
STOP   iteration count == 5  → report current score + remaining items
```

## Next Steps

- Just want a single read, not a loop? → `skills/check-pr.md`
- Fixing the flagged comments? → `skills/implementer.md` (minimal diff, gates apply)
- A flagged item is a real bug? → `skills/diagnose.md` first
- Hit the 5-iteration cap unresolved? → report state, hand back to the user — do not force-merge
