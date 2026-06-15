"""
synthetic_bootstrap.py — Bootstrap the RL loop with synthetic task data.

Instead of waiting for 10+ real runs to get signal, generate synthetic
tasks, score them against the existing skill rules, and feed the results
into the reward log. This gives prompt_evolution and gate_evolution
enough data to start making real decisions.

Usage:
    from synthetic_bootstrap import SyntheticBootstrap

    boot = SyntheticBootstrap(reward_log)
    boot.run()  # generates + scores synthetic tasks

Synthetic tasks are realistic coding scenarios with known-good and
known-bad implementations. The scoring is deterministic (gate checks +
pattern matching), not LLM-dependent.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from reward_log import RewardLog

# Synthetic task definitions
# Each has a task_type, a "good" implementation pattern, and a "bad" one.
SYNTHETIC_TASKS = [
    {
        "id": "syn_auth_01",
        "type": "auth",
        "title": "Create JWT auth middleware",
        "good": {
            "diff": (
                "--- /dev/null\n+++ b/middleware/auth.ts\n"
                "@@ -0,0 +1,20 @@\n"
                "+import jwt from 'jsonwebtoken';\n"
                "+import { Request, Response, NextFunction } from 'express';\n"
                "+\n"
                "+export function authMiddleware(req: Request, res: Response, next: NextFunction) {\n"
                "+  const token = req.headers.authorization?.split(' ')[1];\n"
                "+  if (!token) {\n"
                "+    return res.status(401).json({ error: 'No token provided' });\n"
                "+  }\n"
                "+  try {\n"
                "+    const decoded = jwt.verify(token, process.env.JWT_SECRET!);\n"
                "+    req.user = decoded;\n"
                "+    next();\n"
                "+  } catch (err) {\n"
                "+    return res.status(401).json({ error: 'Invalid token' });\n"
                "+  }\n"
                "+}\n"
            ),
            "review_findings": [],
            "critique_predictions": [],
        },
        "bad": {
            "diff": (
                "--- /dev/null\n+++ b/middleware/auth.ts\n"
                "@@ -0,0 +1,10 @@\n"
                "+import jwt from 'jsonwebtoken';\n"
                "+\n"
                "+export function authMiddleware(req, res, next) {\n"
                "+  const token = req.headers.authorization.split(' ')[1];\n"
                "+  const decoded = jwt.verify(token, 'hardcoded-secret');\n"
                "+  req.user = decoded;\n"
                "+  next();\n"
                "+}\n"
            ),
            "review_findings": [
                "hardcoded secret in auth middleware [auth.ts:5]",
                "missing null check on authorization header [auth.ts:4]",
                "no try-catch on jwt.verify [auth.ts:5]",
            ],
            "critique_predictions": [
                "hardcoded secret",
                "null check missing",
            ],
        },
    },
    {
        "id": "syn_api_01",
        "type": "api",
        "title": "Create REST endpoint for user CRUD",
        "good": {
            "diff": (
                "--- /dev/null\n+++ b/routes/users.ts\n"
                "@@ -0,0 +1,30 @@\n"
                "+import { Router, Request, Response } from 'express';\n"
                "+import { body, validationResult } from 'express-validator';\n"
                "+\n"
                "+const router = Router();\n"
                "+\n"
                "+router.post('/users',\n"
                "+  body('email').isEmail(),\n"
                "+  body('name').notEmpty().trim(),\n"
                "+  async (req: Request, res: Response) => {\n"
                "+    const errors = validationResult(req);\n"
                "+    if (!errors.isEmpty()) {\n"
                "+      return res.status(400).json({ errors: errors.array() });\n"
                "+    }\n"
                "+    try {\n"
                "+      const user = await createUser(req.body);\n"
                "+      res.status(201).json(user);\n"
                "+    } catch (err) {\n"
                "+      res.status(500).json({ error: 'Internal server error' });\n"
                "+    }\n"
                "+  }\n"
                "+);\n"
                "+\n"
                "+export default router;\n"
            ),
            "review_findings": [],
            "critique_predictions": [],
        },
        "bad": {
            "diff": (
                "--- /dev/null\n+++ b/routes/users.ts\n"
                "@@ -0,0 +1,15 @@\n"
                "+import { Router } from 'express';\n"
                "+\n"
                "+const router = Router();\n"
                "+\n"
                "+router.post('/users', async (req, res) => {\n"
                "+  const user = await createUser(req.body);\n"
                "+  console.log('Created user:', user);\n"
                "+  res.json(user);\n"
                "+});\n"
                "+\n"
                "+export default router;\n"
            ),
            "review_findings": [
                "no input validation on user creation [users.ts:6]",
                "console.log in production code [users.ts:7]",
                "no error handling on createUser [users.ts:6]",
                "missing try-catch [users.ts:6]",
            ],
            "critique_predictions": [
                "no input validation",
                "missing error handling",
            ],
        },
    },
    {
        "id": "syn_data_01",
        "type": "data",
        "title": "Add database connection pool",
        "good": {
            "diff": (
                "--- /dev/null\n+++ b/lib/db.ts\n"
                "@@ -0,0 +1,25 @@\n"
                "+import { Pool } from 'pg';\n"
                "+\n"
                "+const pool = new Pool({\n"
                "+  connectionString: process.env.DATABASE_URL,\n"
                "+  max: 20,\n"
                "+  idleTimeoutMillis: 30000,\n"
                "+  connectionTimeoutMillis: 2000,\n"
                "+});\n"
                "+\n"
                "+pool.on('error', (err) => {\n"
                "+  console.error('Unexpected pool error:', err);\n"
                "+  process.exit(1);\n"
                "+});\n"
                "+\n"
                "+export async function query(text: string, params?: unknown[]) {\n"
                "+  const start = Date.now();\n"
                "+  const result = await pool.query(text, params);\n"
                "+  const duration = Date.now() - start;\n"
                "+  return result;\n"
                "+}\n"
                "+\n"
                "+export default pool;\n"
            ),
            "review_findings": [],
            "critique_predictions": [],
        },
        "bad": {
            "diff": (
                "--- /dev/null\n+++ b/lib/db.ts\n"
                "@@ -0,0 +1,8 @@\n"
                "+import { Pool } from 'pg';\n"
                "+\n"
                "+const pool = new Pool({\n"
                "+  connectionString: 'postgresql://user:pass@localhost:5432/mydb',\n"
                "+});\n"
                "+\n"
                "+export default pool;\n"
            ),
            "review_findings": [
                "hardcoded database credentials [db.ts:4]",
                "no connection pool size limit [db.ts:3]",
                "no error handler on pool [db.ts:3]",
            ],
            "critique_predictions": [
                "hardcoded credentials",
                "no connection limits",
            ],
        },
    },
    {
        "id": "syn_ui_01",
        "type": "ui",
        "title": "Create a modal component with form",
        "good": {
            "diff": (
                "--- /dev/null\n+++ b/components/Modal.tsx\n"
                "@@ -0,0 +1,35 @@\n"
                "+import { useEffect, useRef, useCallback } from 'react';\n"
                "+\n"
                "+interface ModalProps {\n"
                "+  isOpen: boolean;\n"
                "+  onClose: () => void;\n"
                "+  children: React.ReactNode;\n"
                "+}\n"
                "+\n"
                "+export function Modal({ isOpen, onClose, children }: ModalProps) {\n"
                "+  const ref = useRef<HTMLDialogElement>(null);\n"
                "+\n"
                "+  useEffect(() => {\n"
                "+    if (isOpen) {\n"
                "+      ref.current?.showModal();\n"
                "+    } else {\n"
                "+      ref.current?.close();\n"
                "+    }\n"
                "+  }, [isOpen]);\n"
                "+\n"
                "+  const handleEscape = useCallback((e: KeyboardEvent) => {\n"
                "+    if (e.key === 'Escape') onClose();\n"
                "+  }, [onClose]);\n"
                "+\n"
                "+  useEffect(() => {\n"
                "+    document.addEventListener('keydown', handleEscape);\n"
                "+    return () => document.removeEventListener('keydown', handleEscape);\n"
                "+  }, [handleEscape]);\n"
                "+\n"
                "+  return <dialog ref={ref}>{children}</dialog>;\n"
                "+}\n"
            ),
            "review_findings": [],
            "critique_predictions": [],
        },
        "bad": {
            "diff": (
                "--- /dev/null\n+++ b/components/Modal.tsx\n"
                "@@ -0,0 +1,15 @@\n"
                "+import { useState } from 'react';\n"
                "+\n"
                "+export function Modal({ isOpen, onClose, children }) {\n"
                "+  const [visible, setVisible] = useState(isOpen);\n"
                "+\n"
                "+  return (\n"
                "+    <div style={{ display: visible ? 'block' : 'none' }}>\n"
                "+      <div onClick={() => { setVisible(false); onClose(); }}>\n"
                "+        {children}\n"
                "+      </div>\n"
                "+    </div>\n"
                "+  );\n"
                "+}\n"
            ),
            "review_findings": [
                "no TypeScript types on props [Modal.tsx:3]",
                "stale state: visible initialized from isOpen but never synced [Modal.tsx:4]",
                "clicking backdrop closes without confirmation [Modal.tsx:8]",
                "no keyboard accessibility (Escape key) [Modal.tsx:3]",
                "using inline styles instead of CSS [Modal.tsx:7]",
            ],
            "critique_predictions": [
                "stale state between isOpen and visible",
                "no keyboard accessibility",
            ],
        },
    },
    {
        "id": "syn_infra_01",
        "type": "infra",
        "title": "Add rate limiting to API endpoints",
        "good": {
            "diff": (
                "--- /dev/null\n+++ b/middleware/rateLimit.ts\n"
                "@@ -0,0 +1,25 @@\n"
                "+import rateLimit from 'express-rate-limit';\n"
                "+import RedisStore from 'rate-limit-redis';\n"
                "+\n"
                "+export const apiLimiter = rateLimit({\n"
                "+  store: new RedisStore({\n"
                "+    sendCommand: (...args: string[]) => redisClient.sendCommand(args),\n"
                "+  }),\n"
                "+  windowMs: 15 * 60 * 1000,\n"
                "+  max: 100,\n"
                "+  standardHeaders: true,\n"
                "+  legacyHeaders: false,\n"
                "+  message: { error: 'Too many requests, please try again later.' },\n"
                "+});\n"
                "+\n"
                "+export const authLimiter = rateLimit({\n"
                "+  windowMs: 15 * 60 * 1000,\n"
                "+  max: 5,\n"
                "+  skipSuccessfulRequests: false,\n"
                "+  message: { error: 'Too many login attempts.' },\n"
                "+});\n"
            ),
            "review_findings": [],
            "critique_predictions": [],
        },
        "bad": {
            "diff": (
                "--- /dev/null\n+++ b/middleware/rateLimit.ts\n"
                "@@ -0,0 +1,10 @@\n"
                "+const requestCounts = {};\n"
                "+\n"
                "+export function rateLimit(req, res, next) {\n"
                "+  const ip = req.ip;\n"
                "+  requestCounts[ip] = (requestCounts[ip] || 0) + 1;\n"
                "+  if (requestCounts[ip] > 100) {\n"
                "+    return res.status(429).json({ error: 'Too many requests' });\n"
                "+  }\n"
                "+  next();\n"
                "+}\n"
            ),
            "review_findings": [
                "in-memory rate limit counter — resets on restart [rateLimit.ts:1]",
                "no window/timer — counter grows forever [rateLimit.ts:1]",
                "unbounded memory — requestCounts grows with every IP [rateLimit.ts:1]",
                "no TypeScript types [rateLimit.ts:3]",
                "no standard rate limit headers [rateLimit.ts:3]",
            ],
            "critique_predictions": [
                "memory leak in counter",
                "no time window on rate limit",
            ],
        },
    },
]


@dataclass
class SyntheticScore:
    """Score for a synthetic implementation."""
    task_id: str
    task_type: str
    variant: str
    gate_pass: bool
    test_pass: bool
    review_findings: list[str]
    critique_predictions: list[str]
    scope_clean: bool
    attempt_count: int


class SyntheticBootstrap:
    """
    Bootstrap the reward log with synthetic task data.
    Uses deterministic scoring (gate checks + pattern matching),
    not LLM calls.
    """

    def __init__(self, reward_log: RewardLog):
        self.reward_log = reward_log
        self.gate_patterns = [
            (r"console\.log\s*\(", "console.log in production"),
            (r"(api[_-]?key|password|token|secret)\s*[:=]\s*[\"'][^'\"]{4,}", "hardcoded secret"),
            (r"@ts-(ignore|nocheck)", "ts suppression"),
            (r"eval\s*\(", "eval usage"),
        ]

    def run(self) -> dict:
        """
        Generate and score all synthetic tasks.
        Returns summary of what was recorded.
        """
        results = {
            "tasks_scored": 0,
            "tasks_skipped": 0,
            "good_scores": [],
            "bad_scores": [],
        }

        for task in SYNTHETIC_TASKS:
            # Score good implementation
            good_score = self._score(task["good"]["diff"], task["good"])
            good = SyntheticScore(
                task_id=task["id"] + "_good",
                task_type=task["type"],
                variant="v_good",
                gate_pass=not self._has_gate_violations(task["good"]["diff"]),
                test_pass=True,  # good impl always passes tests
                review_findings=task["good"]["review_findings"],
                critique_predictions=task["good"]["critique_predictions"],
                scope_clean=True,
                attempt_count=1,
            )

            # Score bad implementation
            bad = SyntheticScore(
                task_id=task["id"] + "_bad",
                task_type=task["type"],
                variant="v_bad",
                gate_pass=not self._has_gate_violations(task["bad"]["diff"]),
                test_pass=False,  # bad impl fails tests
                review_findings=task["bad"]["review_findings"],
                critique_predictions=task["bad"]["critique_predictions"],
                scope_clean=True,
                attempt_count=3,
            )

            # Record both — idempotently (skip if this synthetic id is present)
            for score in (good, bad):
                if self._record(score):
                    results["tasks_scored"] += 1
                else:
                    results["tasks_skipped"] += 1
            results["good_scores"].append(self._compute_composite(good))
            results["bad_scores"].append(self._compute_composite(bad))

        return results

    def _score(self, diff: str, spec: dict) -> dict:
        """Deterministic scoring of a diff."""
        return {
            "gate_pass": not self._has_gate_violations(diff),
            "review_findings": spec.get("review_findings", []),
            "critique_predictions": spec.get("critique_predictions", []),
        }

    def _has_gate_violations(self, diff: str) -> bool:
        """Check if diff has obvious gate violations."""
        for line in diff.split("\n"):
            if not line.startswith("+") or line.startswith("+++"):
                continue
            code = line[1:].strip()
            for pattern, _ in self.gate_patterns:
                if re.search(pattern, code):
                    return True
        return False

    def _record(self, score: SyntheticScore) -> bool:
        """Record a synthetic score. Returns False if already seeded (idempotent)."""
        if self.reward_log.has_task(score.task_id):
            return False
        self.reward_log.record(
            task_id=score.task_id,
            task_type=score.task_type,
            prompt_variant=score.variant,
            gate_pass=score.gate_pass,
            test_pass=score.test_pass,
            review_findings=score.review_findings,
            critique_predictions=score.critique_predictions,
            scope_clean=score.scope_clean,
            attempt_count=score.attempt_count,
        )
        return True

    def _compute_composite(self, score: SyntheticScore) -> float:
        """Compute what the composite score would be."""
        from reward_log import _composite_score, _critique_accuracy
        return _composite_score(
            gate_pass=score.gate_pass,
            test_pass=score.test_pass,
            review_findings=score.review_findings,
            critique_accuracy=_critique_accuracy(
                score.critique_predictions, score.review_findings
            ),
            scope_clean=score.scope_clean,
            attempt_count=score.attempt_count,
        )


if __name__ == "__main__":
    import os
    import sys

    # By default, seed the REAL reward log (memory/rewards.db) so prompt and
    # gate evolution have signal on the first real pipeline run. Idempotent —
    # re-running skips already-seeded tasks. Pass --demo for a throwaway DB.
    demo = "--demo" in sys.argv
    db_path = "/tmp/test_synthetic.db" if demo else None  # None -> default DEFAULT_DB
    log = RewardLog(db_path)
    boot = SyntheticBootstrap(log)

    results = boot.run()
    print(f"Seeded {results['tasks_scored']} synthetic rewards "
          f"({results['tasks_skipped']} already present) "
          f"-> {log.db_path}")
    print(f"Good avg: {sum(results['good_scores'])/len(results['good_scores']):.3f}")
    print(f"Bad avg: {sum(results['bad_scores'])/len(results['bad_scores']):.3f}")
    print(f"\n{log.dashboard()}")

    # Test prompt evolution with synthetic data
    from prompt_evolution import PromptEvolution
    evo = PromptEvolution(log)
    best = evo.select("auth", "implementer")
    print(f"\nBest variant for auth: {best}")

    # Test gate evolution with synthetic data
    from gate_evolution import GateEvolution
    gevo = GateEvolution(log)
    candidates = gevo.find_candidates(min_count=2)
    print(f"Gate candidates: {len(candidates)}")
    for c in candidates:
        result = gevo.test_candidate(c)
        print(f"  [{c.source_count}x] {c.pattern[:50]} -> {result.approved}")

    log.close()
    if demo:
        os.remove("/tmp/test_synthetic.db")
    print("\nSynthetic bootstrap: OK")
