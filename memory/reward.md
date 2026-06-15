# REWARD — Positive Signal (wins per skill)

The reinforcement counterpart to `mistakes.md`. Records per-skill WINS so the retro
sees the NET, not just failures:

- **CLEAN**  — a phase passed every gate on the first try (full reward, 3 pts).
- **SOLVED** — a gate caught an error that was then fixed + re-verified (1 pt).

A bare "capture" is NOT rewarded — that would pay the agent to introduce bugs. Net
quality only: not erring beats recovering.

SIGNAL ONLY — informs the human-gated retro (promote repeated CLEANs to a DISCIPLINE;
don't over-correct a skill whose wins outweigh its failures). It NEVER auto-edits a
skill, changes routing, or feeds the eval score. Written by the conductor;
`harness/reward.py` reads/surfaces it.

<!-- New entries go below this line -->
## [2026-06-14T09:12:52Z] CLEAN | AUTO-LOGGED
**Win**    : IMPLEMENT clean: implement and build a new sale badge component, add it to the product page
**Skill**  : nextjs-rules
**Gate**   : all_gates
**Points** : 3

## [2026-06-14T09:12:22Z] CLEAN | AUTO-LOGGED
**Win**    : IMPLEMENT clean: add a sale badge to the product page
**Skill**  : none
**Gate**   : all_gates
**Points** : 3

