"""
classify.py — Task group classifier for GRPO scoring.

Provides a single public function `classify_task_group(task)` that returns
a deterministic string key grouping similar tasks together for fair
scoring comparison.

Strategy (from build guide §5.2):
  1. Start with `task.discipline` as the group label.
  2. If tags contain a meaningful category keyword (auth, ui, api, data, infra),
     append a suffix to refine the group (e.g. "implement:auth").

The function is deterministic: same Task → same group label every call.
"""

from __future__ import annotations

from task_db import Task

# Category keywords that can refine a discipline-based group.
# Listed in priority order — the first tag matching any of these wins.
_CATEGORY_KEYWORDS = frozenset({"auth", "ui", "api", "data", "infra"})


def classify_task_group(task: Task) -> str:
    """Return a deterministic group label for *task*.

    The label is based on ``task.discipline``, optionally refined by
    a category keyword found in ``task.tags``.

    Returns
    -------
    str
        Group label such as ``"implement"``, ``"review"``,
        ``"implement:auth"``, ``"tdd:ui"``.
    """
    label: str = task.discipline

    # Tags are a freeform list[str]; search for the first keyword match.
    for tag in task.tags:
        # Normalise: lowercase and strip whitespace for reliable matching.
        normalised = tag.strip().lower()
        if normalised in _CATEGORY_KEYWORDS:
            label = f"{task.discipline}:{normalised}"
            break

    return label
