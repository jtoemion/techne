---
name: check-pr
description: Check a pull request for failing checks, unresolved review comments, and an incomplete description, then optionally fix and resolve. Use when preparing a PR to merge or addressing review feedback. One pass — for an iterate-to-perfect loop use greploop.
triggers:
  - check pull request
  - review comments
  - address review feedback
  - prepare to merge
  - pull request status
---

# Check PR

> Adapted from greptileai/skills (MIT). GitHub-first; GitLab/Perforce follow the same shape.

## The One Rule

**Wait for every check to finish before you analyze.** A red check mid-run is
noise; only a terminal state is signal. Then triage every issue into exactly one
bucket: **Actionable | Informational | Already-addressed.**

## Loop

```
1. Identify the PR        gh pr view --json number,headRefName,headRefOid
2. Wait for checks        poll statusCheckRollup until none are PENDING/IN_PROGRESS
3. Gather signal          description + status checks + inline + general comments
4. Categorize each issue  Actionable | Informational | Already-addressed
5. Report                 one table (Area | Issue | Status | Action)
6. Fix (if asked)         make changes → commit → push
7. Resolve threads        resolve addressed/informational review threads
```

## Gather (GitHub)

```bash
gh pr view <N> --json title,body,state,reviews,comments,headRefName,statusCheckRollup
gh api repos/{owner}/{repo}/pulls/<N>/comments                       # inline
gh api --paginate "repos/{owner}/{repo}/issues/<N>/comments?per_page=100"  # general
```

Bot summaries (e.g. `greptile-apps[bot]`) are often **edited in place** — read
the latest by `updated_at`, not the newest created. A current edited summary can
hold actionable items even when inline comments are zero.

## Categorize

```
Actionable        code/test/fix needed
Informational     FYI, question, "looks good" — no change
Already-addressed resolved by a later commit
```

## Report

```
| Area          | Issue                       | Status        | Action Needed            |
| Status Checks | CI build failing            | Failing       | Fix type error src/api.ts|
| Review        | "add null check" @reviewer  | Actionable    | Add guard clause         |
| Description   | TODO in test plan           | Actionable    | Fill test plan           |
| Review        | "looks good" @teammate      | Informational | None                     |
```

## Fix + Resolve (only if the user asks)

```bash
git add <files> && git commit -m "address review feedback" && git push
# then resolve each addressed thread:
gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:"<ID>"}){ thread { isResolved } } }'
```

A failing check is a bug — don't blind-fix. Drop into `skills/diagnose.md` first.

## Next Steps

- Want it iterated to a perfect review, not just checked once? → `skills/greploop.md`
- A status check is failing? → `skills/diagnose.md` (build the repro before fixing)
- Making the actual code fixes? → `skills/implementer.md`
- GitLab/Perforce? → same loop: `glab mr` / `p4 describe -S`, resolve via discussions / Swarm
