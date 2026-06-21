"""
trajectory_queue.py — Multi-trajectory queue for GRPO.

Dispatches N variants of the same task through the pipeline, collects results,
computes group advantages across the batch, and returns ranked comparisons.

This is the piece that makes GRPO a *loop* rather than a post-hoc analysis:
the queue runner dispatches N variants of a task using different prompt
variants, collects results, scores them with advantages, and promotes winners.

Usage:
    from trajectory_queue import TrajectoryQueue, compare_variants

    queue = TrajectoryQueue(model=my_model, run_tests=my_tests)
    result = queue.run_trajectories(
        {"title": "add rate limiter", "discipline": "tdd", "tags": ["auth"]},
        n_variants=3,
    )
    print(f"Winner: {result.winning_variant} (advantage={result.winning_advantage:.3f})")
    for t in result.trajectories:
        print(f"  {t.variant_name}: advantage={t.advantage:.3f}")

    # Or use the convenience function:
    ranked = compare_variants(task_spec, n_variants=3, model=my_model, run_tests=my_tests)
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from driver import ModelFn, TestFn, PlanResult, TaskRun
from prompt_evolution import PromptEvolution
from reward_log import RewardLog


# ── Data types ──────────────────────────────────────────────────────────────


@dataclass
class TrajectoryResult:
    """Result of running a single trajectory (one prompt variant).

    Attributes
    ----------
    variant_name : str
        Name of the prompt variant used for this trajectory.
    variant_config : dict
        Configuration dict for the variant (system_suffix, temperature, etc.).
    advantage : float
        Average advantage across all tasks in this trajectory.
    avg_score : float
        Average composite score across all tasks in this trajectory.
    completed : bool
        True if all tasks in this trajectory completed (DONE).
    task_runs : list
        List of TaskRun objects from the trajectory.
    error : str
        Error message if the trajectory failed, empty otherwise.
    """
    variant_name: str
    variant_config: dict
    advantage: float = 0.0
    avg_score: float = 0.0
    completed: bool = False
    task_runs: list = field(default_factory=list)
    error: str = ""


@dataclass
class TrajectoryQueueResult:
    """Overall result of a multi-trajectory comparison.

    Attributes
    ----------
    task_spec : dict
        The task specification used for all trajectories.
    trajectories : list[TrajectoryResult]
        All trajectory results, sorted by advantage (descending).
    winning_variant : str
        Name of the variant with the highest advantage.
    winning_advantage : float
        Advantage of the winning variant.
    all_completed : bool
        True if every trajectory completed without error.
    """
    task_spec: dict
    trajectories: list[TrajectoryResult]
    winning_variant: str = ""
    winning_advantage: float = 0.0
    all_completed: bool = False


# ── Trajectory Queue ────────────────────────────────────────────────────────


class TrajectoryQueue:
    """Dispatches N variants of a task through the pipeline and compares results.

    Each trajectory runs the full pipeline (via ``run_plan()``) with a different
    prompt variant. Results are collected into a shared reward log, advantages are
    computed across the batch, and the winning variant is identified.

    Parameters
    ----------
    model : ModelFn
        Model callable for generating agent artifacts
        ``(system, user, phase) -> raw text``.
    run_tests : TestFn
        Test runner callable ``() -> stdout`` (SHA-gated).
    reward_log : RewardLog, optional
        Shared reward log. A fresh one is created if not provided.
    prompt_evolution : PromptEvolution, optional
        Prompt evolution instance. Created from *reward_log* if not provided.
    run_plan_fn : callable, optional
        The ``run_plan()`` implementation. Defaults to ``driver.run_plan``.
        Injectable for testing.
    """

    def __init__(
        self,
        model: ModelFn,
        run_tests: TestFn,
        reward_log: Optional[RewardLog] = None,
        prompt_evolution: Optional[PromptEvolution] = None,
        run_plan_fn: Optional[Callable] = None,
    ):
        self.model = model
        self.run_tests = run_tests
        self.reward_log = reward_log or RewardLog()
        self.evolution = prompt_evolution or PromptEvolution(self.reward_log)
        self._run_plan_fn = run_plan_fn

    # ── Public API ────────────────────────────────────────────────────────

    def run_trajectories(
        self,
        task_spec: dict,
        n_variants: int = 3,
        agent: str = "implementer",
    ) -> TrajectoryQueueResult:
        """Run *n_variants* trajectories with different prompt variants.

        Steps:
        1. Query ``prompt_evolution`` for the current best variant and N-1
           alternatives (existing variants or newly evolved candidates).
        2. Run each variant through ``run_plan()`` as its own trajectory.
        3. Tag all rewards with a shared group label and call
           ``compute_batch_advantages()`` to score the batch.
        4. Refresh per-trajectory advantage scores from the reward log.
        5. Sort trajectories by advantage (descending) and return the winner.

        Parameters
        ----------
        task_spec : dict
            Task specification with ``title``, ``description``, ``tags``,
            ``discipline``, etc. — same format as ``driver.run_plan()``.
        n_variants : int, optional
            Number of variants to try. Default 3 (current best + 2 alternatives).
        agent : str, optional
            Agent role to select variants for. Default ``"implementer"``.

        Returns
        -------
        TrajectoryQueueResult
            Ranked results with winner identification.
        """
        variants = self._get_variants(task_spec, n_variants, agent)

        # Run each variant as a separate trajectory
        trajectories: list[TrajectoryResult] = []
        for variant_name, variant_config in variants:
            traj = self._run_trajectory(task_spec, variant_name, variant_config)
            trajectories.append(traj)

        # Set group label for all tasks in this batch so advantages compare
        # variants head-to-head within the same group.
        group_label = f"trajectory:{task_spec.get('discipline', 'tdd')}"
        self._set_batch_group(group_label)

        # Compute advantages across the whole batch
        self.reward_log.compute_batch_advantages()

        # Refresh per-trajectory advantages from the reward log
        for traj in trajectories:
            self._refresh_trajectory_advantage(traj)

        # Sort by advantage descending
        trajectories.sort(key=lambda t: t.advantage, reverse=True)

        # Identify winner
        all_completed = all(t.completed for t in trajectories)
        winner = trajectories[0] if trajectories else None

        return TrajectoryQueueResult(
            task_spec=task_spec,
            trajectories=trajectories,
            winning_variant=winner.variant_name if winner else "",
            winning_advantage=winner.advantage if winner else 0.0,
            all_completed=all_completed,
        )

    # ── Variant selection ─────────────────────────────────────────────────

    def _get_variants(
        self,
        task_spec: dict,
        n_variants: int = 3,
        agent: str = "implementer",
    ) -> list[tuple[str, dict]]:
        """Get *n_variants* prompt variants: best + alternatives.

        Returns a list of ``(variant_name, config_dict)`` tuples. The first
        entry is always the current best variant (from reward log data, or the
        first available if no data exists). Remaining entries are alternatives
        from the variant pool, excluding the best. If more variants are needed
        than available, ``evolve()`` is called to generate new candidates.

        Parameters
        ----------
        task_spec : dict
            Task spec used to determine the task type from ``discipline``.
        n_variants : int
            Desired number of variants.
        agent : str
            Agent role.

        Returns
        -------
        list[tuple[str, dict]]
            At most *n_variants* ``(name, config)`` pairs.
        """
        task_type = task_spec.get("discipline", "tdd")
        agent_variants = self.evolution.variants.get(agent, {})

        if not agent_variants:
            return [("default", {"description": "default", "system_suffix": "", "temperature": 0.2})]

        # Identify best variant from reward log (or first available)
        best_name = self.reward_log.best_variant(task_type)
        if not best_name or best_name not in agent_variants:
            best_name = next(iter(agent_variants))

        variants = [(best_name, agent_variants[best_name])]

        # Add alternatives, excluding the best
        for alt_name, alt_config in agent_variants.items():
            if alt_name != best_name and len(variants) < n_variants:
                variants.append((alt_name, alt_config))

        # If more are needed, try evolving new candidates
        while len(variants) < n_variants:
            new_name = self.evolution.evolve(task_type, agent)
            if new_name not in [v[0] for v in variants] and new_name in agent_variants:
                variants.append((new_name, agent_variants[new_name]))
            else:
                break

        return variants

    # ── Trajectory execution ──────────────────────────────────────────────

    def _run_trajectory(
        self,
        task_spec: dict,
        variant_name: str,
        variant_config: dict,
    ) -> TrajectoryResult:
        """Run one task with a specific prompt variant.

        Creates an isolated temp TaskDB for each trajectory so task state does
        not leak between variants. The reward log is shared so advantages
        compare across the whole batch.

        If the pipeline run raises an exception, the trajectory is marked
        failed (``error`` is set, ``completed`` is False) — it does NOT
        propagate and crash the batch.
        """
        from task_db import TaskDB

        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        tmp_path = tmp_db.name

        try:
            plan = self._invoke_run_plan(
                [task_spec],
                model=self.model,
                run_tests=self.run_tests,
                db=TaskDB(tmp_path),
                reward_log=self.reward_log,
                prepare_context=False,
                evolve=False,
            )

            # Update reward log with the correct variant name for this
            # trajectory (run_plan defaults to "v1" because it doesn't know
            # about variant selection).
            for task_run in plan.tasks:
                self.reward_log._conn.execute(
                    "UPDATE rewards SET prompt_variant = ? WHERE task_id = ?",
                    (variant_name, task_run.task_id),
                )
            self.reward_log._conn.commit()

            completed = plan.all_done
            return TrajectoryResult(
                variant_name=variant_name,
                variant_config=variant_config,
                completed=completed,
                task_runs=list(plan.tasks),
            )
        except Exception as exc:
            return TrajectoryResult(
                variant_name=variant_name,
                variant_config=variant_config,
                completed=False,
                error=str(exc),
            )
        finally:
            try:
                os.unlink(tmp_path)
            except (OSError, FileNotFoundError):
                pass

    def _invoke_run_plan(self, *args, **kwargs) -> PlanResult:
        """Invoke ``run_plan()``, using injected fn if provided."""
        if self._run_plan_fn is not None:
            return self._run_plan_fn(*args, **kwargs)
        from driver import run_plan
        return run_plan(*args, **kwargs)

    # ── Group / advantage bookkeeping ─────────────────────────────────────

    def _set_batch_group(self, group_label: str) -> None:
        """Set the group label on all rewards without a group.

        After trajectories are recorded, this tags all ungrouped rewards with a
        shared group so ``compute_batch_advantages()`` can compare them.
        """
        self.reward_log._conn.execute(
            'UPDATE rewards SET "group" = ? WHERE "group" = ? OR "group" IS NULL',
            (group_label, ""),
        )
        self.reward_log._conn.commit()

    def _refresh_trajectory_advantage(self, traj: TrajectoryResult) -> None:
        """Read the per-task advantage and composite scores from the reward log.

        Averages across all tasks in the trajectory to compute the trajectory's
        overall ``advantage`` and ``avg_score``.
        """
        advantages = []
        scores = []
        for task_run in traj.task_runs:
            row = self.reward_log._conn.execute(
                "SELECT advantage, composite_score FROM rewards WHERE task_id = ?",
                (task_run.task_id,),
            ).fetchone()
            if row:
                advantages.append(row["advantage"])
                scores.append(row["composite_score"])

        if advantages:
            traj.advantage = sum(advantages) / len(advantages)
        if scores:
            traj.avg_score = sum(scores) / len(scores)


# ── Convenience function ────────────────────────────────────────────────────


def compare_variants(
    task_spec: dict,
    n_variants: int = 3,
    *,
    model: ModelFn,
    run_tests: TestFn,
    reward_log: Optional[RewardLog] = None,
    prompt_evolution: Optional[PromptEvolution] = None,
) -> TrajectoryQueueResult:
    """Run a multi-trajectory comparison and return ranked results.

    Convenience wrapper that creates a ``TrajectoryQueue``, runs the
    comparison, and returns the ranked result.

    Parameters
    ----------
    task_spec : dict
        Task specification dict (title, description, tags, discipline, ...).
    n_variants : int, optional
        Number of variants to compare. Default 3.
    model : ModelFn
        Model callable for generating agent artifacts.
    run_tests : TestFn
        Test runner callable for SHA-gated verification.
    reward_log : RewardLog, optional
        Shared reward log. Fresh one created if not provided.
    prompt_evolution : PromptEvolution, optional
        Prompt evolution instance. Created from *reward_log* if not provided.

    Returns
    -------
    TrajectoryQueueResult
        Ranked trajectories with winning variant identified.
    """
    queue = TrajectoryQueue(
        model=model,
        run_tests=run_tests,
        reward_log=reward_log,
        prompt_evolution=prompt_evolution,
    )
    return queue.run_trajectories(task_spec, n_variants=n_variants)
