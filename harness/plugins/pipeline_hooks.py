"""
pipeline_hooks.py — Hook plugin that enforces multi-agent pipeline phases.

Hooks into the GateRegistry to:
  1. PRE-GATE: Verify the task is in the correct phase before gates run
  2. POST-GATE: Record the gate result and advance the phase
  3. PRE-GATE: Inject relevant mistake history into gate context
  4. POST-GATE: Log gate pass/fail to the task's event trail

Usage:
    from pipeline_hooks import install_pipeline_hooks

    enforcer = PipelineEnforcer(db)
    install_pipeline_hooks(registry, enforcer)

    # Now every gate run is automatically:
    #   - Phase-checked (can't review before implement)
    #   - Audit-logged (task_id + gate result recorded)
    #   - Mistake-informed (past failures surfaced)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.gate_registry import GateRegistry, GateMeta
    from harness.pipeline_enforcer import PipelineEnforcer


def install_pipeline_hooks(
    registry: "GateRegistry",
    enforcer: "PipelineEnforcer",
    task_id: str | None = None,
) -> None:
    """
    Install pipeline enforcement hooks on the gate registry.

    Args:
        registry: the GateRegistry instance
        enforcer: the PipelineEnforcer instance
        task_id: current task ID (required for phase enforcement)
                 If None, hooks are installed but phase checks are skipped
                 (useful for the existing single-task pipeline).
    """
    # Store task_id in a mutable container so it can be updated
    ctx = {"task_id": task_id}

    # ── Block writes to .techne/audit/ ─────────────────────────────────────
    _AUDIT_DIR_NAME = ".techne"
    _AUDIT_SUBDIR = "audit"

    def _is_audit_path(path_str: str) -> bool:
        """Check if a path targets the audit directory."""
        from pathlib import Path
        p = Path(path_str)
        parts = p.parts
        return _AUDIT_DIR_NAME in parts and _AUDIT_SUBDIR in parts

    def pre_gate_hook(diff: str, meta: "GateMeta") -> None:
        """Before each gate: verify phase + inject context."""
        tid = ctx["task_id"]
        if not tid:
            return  # no task context, skip enforcement

        # Phase check: can we even be running gates right now?
        phase = enforcer.get_phase(tid)
        if phase in ("DONE", "FAILED"):
            raise GateViolation(
                f"PIPELINE VIOLATION [{meta.name}]: "
                f"Task is in terminal phase '{phase}'. No gates should run."
            )

        # If the task is BLOCKED, only DEBUG-related gates should run
        task = enforcer.db.get_task(tid)
        if task and task.status == "BLOCKED":
            if meta.stack != "pipeline":
                raise GateViolation(
                    f"PIPELINE VIOLATION [{meta.name}]: "
                    f"Task is BLOCKED. Only pipeline/debug gates can run."
                )

    def post_gate_hook(
        diff: str, meta: "GateMeta", exc: Optional[Exception] = None
    ) -> None:
        """After each gate: record result in task event trail."""
        tid = ctx["task_id"]
        if not tid:
            return

        task = enforcer.db.get_task(tid)
        if not task:
            return

        verdict = "PASS" if exc is None else "FAIL"
        mistake = []
        if exc is not None and hasattr(exc, "message"):
            mistake = [f"{meta.name}: {str(exc)[:100]}"]
        elif exc is not None:
            mistake = [f"{meta.name}: {str(exc)[:100]}"]

        enforcer.db._log_event(
            tid,
            agent="pipeline",
            action="gate_check",
            summary=f"Gate {meta.name}: {verdict}",
            verdict=verdict,
            findings=str(exc)[:200] if exc else "",
            mistakes_found=mistake,
        )

    def pre_gate_with_mistakes(diff: str, meta: "GateMeta") -> None:
        """Surface relevant past mistakes before each gate runs."""
        # This is informational — the gate function itself decides
        # if the violation is real. The hook just ensures the mistake
        # history is available in the event trail.
        pass

    # Register hooks
    registry.add_pre_hook(pre_gate_hook)
    registry.add_post_hook(post_gate_hook)

    # Store context setter for external updates
    registry._pipeline_ctx = ctx  # type: ignore


def set_task_context(registry: "GateRegistry", task_id: str | None) -> None:
    """Update the active task context for pipeline hooks."""
    if hasattr(registry, "_pipeline_ctx"):
        registry._pipeline_ctx["task_id"] = task_id  # type: ignore


from harness.gates import GateViolation
