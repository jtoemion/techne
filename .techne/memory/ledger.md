# Process Ledger — Decisions, Lessons & Disciplines

Records the method layer: what was decided about HOW to work, what was learned
about the process, and what methods worked. Surfaced before every task alongside
mistakes, so past method-lessons inform new work instead of being re-derived.

Kinds: DECISION | LESSON | DISCIPLINE
Status: ACTIVE | ARCHIVED

<!-- New entries go below this line -->
## [2026-06-23T09:08:17Z] LESSON | retro:82f1ade50f4b
**What**   : Commit before IMPLEMENT or the diff gate rejects
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T09:08:17Z] DECISION | retro:82f1ade50f4b
**What**   : logWarn takes plain string (no uid)
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T09:08:17Z] DECISION | retro:82f1ade50f4b
**What**   : logError preserves error.name + message, strips rest
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:53:50Z] LESSON | retro:d81309907f77
**What**   : patch tool corrupts multiline
**Why**    : use write_file
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:53:50Z] DECISION | retro:d81309907f77
**What**   : Named export memo uses const pattern
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:45:55Z] LESSON | retro:c7c6716a09b8
**What**   : Lazy chunks increase PWA precache count
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:45:55Z] DECISION | retro:c7c6716a09b8
**What**   : Calendar named-export via .then(m => ({ default: m.Calendar }))
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:45:55Z] DECISION | retro:c7c6716a09b8
**What**   : Per-route Suspense for independent loading
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:30:08Z] DISCIPLINE | retro:3d650f317c74
**What**   : Stash+test to confirm pre-existing failures
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:30:08Z] LESSON | retro:3d650f317c74
**What**   : vi.mock() inside it() unreliable
**Why**    : use shared mock variables
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:30:08Z] DECISION | retro:3d650f317c74
**What**   : Proxy-then-BYOK fallback
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:30:08Z] DECISION | retro:3d650f317c74
**What**   : Gemini REST API over SDK in CF
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:18:11Z] DISCIPLINE | retro:c849cba07dd7
**What**   : SHA gate checks for PASS indicators
**Why**    : embed them explicitly
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:18:11Z] LESSON | retro:c849cba07dd7
**What**   : Mocking httpsCallable requires nested vi.fn() pattern
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:18:11Z] DECISION | retro:c849cba07dd7
**What**   : phase_mode=fast for self-contained changes
**Why**    : —
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:18:11Z] DECISION | retro:c849cba07dd7
**What**   : verifyPin returns profile data with auth result
**Why**    : eliminates extra client read
**Skill**  : none
**Status** : ACTIVE

## [2026-06-23T08:18:11Z] DECISION | retro:c849cba07dd7
**What**   : rate_limits locked to deny all
**Why**    : CF Admin SDK bypasses rules
**Skill**  : none
**Status** : ACTIVE

