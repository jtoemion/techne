# Agent Knowledge Dimensions

Sources:
- `docs/NickNisi- pipeliene.txt`
- `docs/Eval is broken.txt`
- `docs/harness-findings..txt`
- `docs/harness.txt` (harness-specific digest created from the findings)
- `docs/open-knowledge-format-context.md`
- Existing Techne docs: `docs/techne-domains.md`, `docs/enforcement-operations.md`, `docs/host-integration-guide.md`

Purpose: give future agents a layered, multi-dimensional map of the ideas so they can act quickly without rereading the raw talk summaries.

---

## Dimension 0: One-Screen Thesis

Techne exists because agent quality is not only a model problem. It is a harness problem.

The model writes and reasons. The harness constrains, proves, scores, remembers, and routes. Better agents come from better control loops: small useful skills, deterministic gates, real test evidence, targeted evaluation, and retrospectives that become future guardrails.

The guiding rule:

> Do not trust agent claims. Trust artifacts, gates, logs, hashes, tests, screenshots, videos, diffs, and repeatable evals.

---

## Dimension 1: Coding Principles Layer

Use this layer to prevent the knowledge base from becoming bloated.

| Principle | Meaning for Techne | Agent behavior |
|---|---|---|
| YAGNI | Do not build a massive skill or eval system before a real failure proves it is needed. | Add a guardrail only when it prevents a known miss or unlocks a repeated workflow. |
| KISS | Prefer a small deterministic script over a complex prompt. | If a check can be code, make it code. If it must be prose, keep it short. |
| DRY | Repeated failure logic belongs in one reusable gate, script, or skill card. | Extract repeated operational checks into `scripts/`, `harness/`, or a skill. |

Operational translation:

1. Start with the smallest working gate.
2. Keep skills focused on common gotchas, not full documentation.
3. Add evals for real decision points, not vanity benchmarks.
4. Prefer evidence over confidence.

---

## Dimension 2: Harness Layer

The harness is the spine around the model.

Agent = model + harness. The model reasons; the harness executes, stores state,
limits scope, verifies outputs, manages tools, and enforces policy.

It is responsible for:

| Harness job | Why it matters | Techne location |
|---|---|---|
| Phase routing | Keeps work moving through recall, implementation, review, verify, eval, retro, and conclude. | `harness/orchestrator_loop.py`, `harness/driver.py` |
| Deterministic gates | Prevents agents from self-reporting success without proof. | `harness/gates.py`, `scripts/*` |
| Evidence capture | Stores test output, hashes, reports, and artifacts. | `.techne/reports/`, `.techne/logs/`, `scripts/pipeline_health.py` |
| Skill loading | Gives the model only the useful instructions for the task. | `harness/phase_skills.py`, `skills/skill-router.yaml` |
| Learning loop | Turns failures into safer future behavior. | `harness/reward_log.py`, `harness/apply_retro.py`, `docs/retro/` |

Five core subsystems:

| Subsystem | Job |
|---|---|
| Instructions | Provide layered, scoped context instead of one giant prompt. |
| State | Persist progress and decisions across sessions. |
| Verification | Require empirical proof before completion. |
| Scope | Keep execution bounded, usually one feature at a time. |
| Lifecycle | Make startup, shutdown, and handoff restartable. |

Core lesson from Nick Nisi:

> Agent reliability improves when behavior is enforced by a state machine and proof gates, not by longer prompts.

Core lesson from Kaggle/DeepMind:

> When measuring agents, the harness can change the result as much as the model. Evaluate the wrapper, not just the brain.

---

## Dimension 3: State And Lifecycle Layer

Agents forget. Harnesses remember.

The harness findings describe an ACID-like model for agent state:

| Principle | Techne meaning |
|---|---|
| Atomicity | Each logical increment should have a checkpoint, commit, or task event. |
| Consistency | Persist state only when verification passes. |
| Isolation | Parallel agents need separate branches, task IDs, or progress files. |
| Durability | Important progress and decisions must live on disk. |

Cold-start test for any future agent:

1. What is this system?
2. How is it organized?
3. How do I run and verify it?
4. What is the current progress?

If those answers require a human explanation, the harness state layer is weak.

Use structured files for machine-resumable state. Use decision records for the
"why" behind architecture choices.

---

## Dimension 4: Proof Layer

Agents often say "tests passed" or "I verified it" without enough evidence. The proof layer defines what counts.

| Claim | Weak evidence | Strong evidence |
|---|---|---|
| Tests passed | Agent says so. | Captured command output plus stable hash. |
| UI works | Agent describes it. | Playwright screenshot/video or DOM assertion. |
| Review is clean | Agent summary. | Structured findings with file/line references and no unresolved hard fails. |
| Eval improved | One anecdote. | Repeated eval cases with comparable inputs and scored outputs. |
| Context was read | "I checked docs." | Listed files, relevant excerpts, and downstream decisions based on them. |

Use SHA-gated outputs for test proof when possible. Use screenshots or videos for visual/UI proof. Use structured reports for review proof.

If proof is expensive, state the residual risk instead of pretending certainty.

---

## Dimension 5: Context And Skill Layer

The Nick Nisi note contains the most important warning for Techne skills:

> More documentation can make agents worse.

The harness findings make the same point through context engineering: giant root
instruction files create "lost in the middle" failures. Root instructions should
be maps, not encyclopedias.

Skill design should follow this shape:

| Bad skill shape | Better skill shape |
|---|---|
| Full library documentation copied into context. | Short list of landmines and project-specific gotchas. |
| General coding advice the model already knows. | Rules that are surprising in this repo. |
| Long prose with no trigger boundary. | Compact trigger, red flags, checks, and next step. |
| "Always do everything." | "When you see X, check Y before touching Z." |

Skill writing rule:

1. Name the failure the skill prevents.
2. Name the trigger that loads it.
3. Name the exact check or action.
4. Keep it small enough that the agent can actually obey it.

For durable building context, use the OKF-style convention in
`docs/open-knowledge-format-context.md`: one concept per markdown file, YAML
frontmatter for structured metadata, markdown links for graph edges, and
`index.md`/`log.md` for navigation and chronology.

---

## Dimension 6: Execution Loop Layer

Use ReAct and PEV together:

| Pattern | Meaning for Techne |
|---|---|
| ReAct | Reason, act through tools, observe real output, feed observations back. |
| PEV | Plan, execute against the plan, verify against explicit acceptance criteria. |

Planning and execution should stay separate enough that verification can judge
the result against a prior contract, not against the builder's self-assessment.

Every loop needs limits:

- Step budget
- Time budget
- Token budget
- Cost budget

If a budget runs out, the agent should return a structured failure artifact
instead of continuing an invisible loop.

---

## Dimension 7: Evaluation Layer

The Kaggle eval note says benchmarks are broken because they are static, opaque, stale, and too narrow.

Techne should treat evals as operational instruments, not trophies.

| Eval type | Use when | Example |
|---|---|---|
| Regression eval | A known failure must not return. | Agent previously skipped tests; eval requires captured test hash. |
| Harness isolation eval | Need to know whether the model or wrapper failed. | Same task, same tools, different model or prompt. |
| Pairwise eval | Choosing between two prompts, skills, or gates. | Old skill vs reduced gotcha-only skill. |
| Safety preflight | Action is high impact. | Deleting files, changing auth, data migration. |
| PvP/arena eval | Need ongoing ranking where tasks can saturate. | Multiple strategies compete on repeated benchmark tasks. |

Evaluation warning:

If an eval changes the surrounding tool flow, it may be measuring the harness more than the model. That is not bad, but name it honestly.

---

## Dimension 8: Policy And Supply Chain Layer

This layer matters when agent work moves from local code changes into CI/CD,
deployment, or infrastructure.

| Control | Meaning |
|---|---|
| SHA pinning | Deploy immutable artifacts, not mutable tags like `latest`. |
| SLSA provenance | Prove where, how, and by whom an artifact was built. |
| SBOM gate | Block risky licenses, deprecated packages, or vulnerability thresholds. |
| OPA/Rego policy | Deny unsafe actions using deterministic policy-as-code. |
| Cosign/signatures | Verify artifact authenticity before deployment. |

Rule:

No production action should depend on an agent's claim. It should depend on
immutable identifiers, signed artifacts, provenance, and policy gates.

---

## Dimension 9: Tool And Authorization Layer

Tool access is part of the harness, not part of the model.

MCP-style gateways are useful because they shrink a huge API surface into a
small number of routed tools while keeping credentials outside the model.

Agent-safe tool rule:

> The model proposes actions. The harness authenticates, authorizes, executes, and returns observations.

Watch for authorization propagation. A subagent should not accidentally inherit
the parent agent's full power. Delegation messages need scoped permissions, and
each tool call should check that scope.

---

## Dimension 10: Failure Mode Layer

Use this when an agent gets stuck or when a new guardrail is proposed.

| Failure mode | Symptom | Better response |
|---|---|---|
| Context bloat | Agent ignores important instruction in huge skill/doc payload. | Delete broad docs; keep task-specific gotchas. |
| False verification | Agent claims tests passed without output. | Require command output, hash, or artifact path. |
| Prompt-only enforcement | Agent forgets required phase or skips a check. | Move rule into a deterministic gate. |
| Stale benchmark | Eval becomes too easy or irrelevant. | Refresh cases from recent failures and user workflows. |
| Harness contamination | Eval result shifts because tool wrapper changed. | Run harness isolation test. |
| Doom loop | Agent repeats the same failed approach. | Write a retro note and convert the lesson into a skill/gate. |
| Overbuilding | New system adds complexity before proving need. | Apply YAGNI: write one focused check first. |
| Mutable artifact drift | Deployment changes without source change. | Pin by SHA/digest and verify provenance. |
| Authorization leak | Delegated agent uses parent-level permissions. | Propagate scoped auth and check it per action. |
| State loss | New agent cannot resume without a human summary. | Add structured progress and decision artifacts. |

---

## Dimension 11: Architecture Mapping Layer

This maps the talk ideas into Techne components.

| External idea | Techne interpretation | Candidate implementation |
|---|---|---|
| State-machine agent harness | Pipeline phases must be explicit and gated. | `orchestrator_loop.py`, `next.py`, phase state. |
| Implementer/verifier/reviewer/closer/retro agents | Separate roles reduce confused responsibilities. | `agents/*.md`, phase-specific skills. |
| Cryptographic proof of test runs | Do not trust test claims. | `harness/sha_gate.py`, `.techne/reports/verify/test_output.txt`. |
| Playwright visual proof | UI changes need visual evidence. | Webapp testing skill, Playwright scripts, saved screenshots/videos. |
| Delete bloated skills | Skills should be small, sharp, and gotcha-focused. | Skill pruning and router tests. |
| Community/niche benchmarks | Eval cases should come from real user/project failures. | `tests/evals/cases/*.json`, retro-derived evals. |
| Harness affects score | Compare wrappers as first-class variables. | Harness isolation eval matrix. |
| ACID state | Agent progress must survive context resets. | task DB, checkpoints, decisions docs, task events. |
| PreTool/PostTool/Stop hooks | Enforce safety during tool lifecycle. | phase guards, watchdogs, pipeline hooks. |
| Policy-as-code | Security and deploy rules should be deterministic. | future OPA/Rego policy layer. |
| MCP gateway | Tool access should be small and credential-safe. | routed tool facade around external APIs. |

---

## Dimension 12: Agent Decision Layer

When an agent reads this file, it should make decisions in this order:

1. What is the user's desired outcome?
2. Which Techne domain owns the work?
3. What evidence will prove the work is done?
4. Which harness subsystem is involved: instruction, state, verification, scope, or lifecycle?
5. Is this a code change, docs change, eval change, policy change, or harness change?
6. Is the needed instruction already in a small skill/gate?
7. If adding knowledge, is it a gotcha, proof rule, eval case, state artifact, policy, or domain map?
8. What is the smallest durable artifact that helps the next agent?

Avoid:

- Adding broad documentation because the source material is broad.
- Writing rules that cannot be checked.
- Calling an eval "model quality" when it also changed tools, prompts, or routing.
- Treating a single success as proof of reliability.
- Adding deployment power without immutable proof and scoped authorization.

---

## Dimension 13: Knowledge Artifact Types

Use the right artifact for the right kind of learning.

| Artifact | Stores | Good for | Bad for |
|---|---|---|---|
| Skill | Short behavioral rule for agents. | Repeated gotchas, triggers, red flags. | Long architecture explanation. |
| Gate | Deterministic pass/fail check. | Enforcing proof, format, tests, safety. | Judgment calls. |
| Eval case | Repeatable scored task. | Comparing changes over time. | Explaining architecture. |
| Retro | What happened and what to change next. | Learning from a specific run. | Permanent broad rules. |
| Domain doc | Stable map of system parts. | Orientation and ownership. | Fast task-specific instructions. |
| Source note | Raw external idea. | Traceability. | Direct agent context every run. |
| Policy | Deterministic infrastructure/security rule. | Blocking unsafe deploys or API actions. | Soft guidance. |
| State file | Machine-readable progress. | Resuming after context reset. | Narrative explanation. |
| OKF concept file | One durable concept with frontmatter and links. | Shared building context. | Raw transcript dumps. |

Rule of thumb:

Raw notes become dimensions. Dimensions become gates, skills, or evals only when a repeated workflow needs them.

---

## Dimension 14: Backlog Layer

Candidate work derived from the source notes:

| Priority | Work item | Reason |
|---|---|---|
| High | Add a lightweight harness isolation eval template. | Kaggle note says harness changes can swing performance dramatically. |
| High | Audit current skills for context bloat. | Nick Nisi note shows exhaustive skills can reduce accuracy. |
| High | Ensure test verification always captures output and hash. | Prevents false verification. |
| High | Add a cold-start checklist to host/agent docs. | Harness findings say agents should resume from disk context. |
| High | Identify which state artifacts should be JSON vs Markdown. | Structured state resists agent corruption. |
| High | Adopt OKF-style concept files for `.techne/context/`. | Makes building context portable, versioned, and agent-readable. |
| Medium | Add a UI proof recipe for Playwright screenshots/videos. | Useful for frontend tasks, but heavier than normal tests. |
| Medium | Add pairwise eval runner for skill/prompt changes. | Helps compare two approaches without vibes. |
| Medium | Add retro-to-eval promotion rule. | Repeated failures should become eval cases. |
| Medium | Sketch an OPA/SLSA future gate plan. | Deployment safety should become policy, not prompt advice. |
| Medium | Define scoped authorization for delegated subagents. | Prevents authorization propagation leaks. |
| Low | Explore arena-style evals. | Useful later, but likely expensive and overkill now. |
| Low | Track decentralized proof-of-inference as inspiration. | Interesting long-horizon idea, not near-term Techne scope. |

---

## Dimension 15: Quick Agent Digest

If you only have 60 seconds:

1. Techne is a harness, not just a prompt set.
2. Harness quality can change agent performance by large margins.
3. Small gotcha-focused skills beat giant documentation dumps.
4. Agents need structured state because context windows forget.
5. Agents need proof gates because self-reported success is unreliable.
6. Evals should test real workflows and separate model quality from wrapper quality.
7. CI/CD needs immutable SHA/digest proof, policy gates, and provenance.
8. Tool permissions must stay scoped through delegation.
9. Every repeated failure should become either a skill, gate, eval, policy, state artifact, or retro note.
10. Apply YAGNI, KISS, and DRY before adding new machinery.
