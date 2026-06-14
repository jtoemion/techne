"""
session.py — multi-agent session log.

Writes a structured SESSION.md that any agent (Claude, OpenCode, Hermes)
can read cold with zero prior context. Designed for handoff, not just
retrospection.

Every pipeline run overwrites memory/SESSION.md (current state).
A timestamped archive copy is saved to memory/sessions/.

Session log is tool-agnostic: plain markdown, no internal references,
no assumption about which tool reads it next.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
MEMORY_DIR = ROOT / "memory"
SESSION_FILE = MEMORY_DIR / "SESSION.md"
SESSIONS_DIR = MEMORY_DIR / "sessions"


def project_name(root: Path = ROOT) -> str:
    """The project's name — stable across git worktrees. A worktree lives at
    `<repo>/.claude/worktrees/<name>`, so `root.name` there is the worktree's, not
    the project's. Walk back to the real repo name in that case."""
    if root.parent.name == "worktrees" and root.parent.parent.name == ".claude":
        return root.parent.parent.parent.name
    return root.name

SESSION_TEMPLATE = """\
---
session_id: {session_id}
timestamp: {timestamp}
agent_tool: {agent_tool}
project: {project}
status: {status}
eval_score: {eval_score}
---

# Session: {task}

## What Was Done

{what_done}

## Files Changed

{files_changed}

## Decisions Made

{decisions}

## Mistakes Logged

{mistakes}

## Eval Score: {eval_score}/100 ({eval_grade})

{eval_summary}

## Open Questions

{open_questions}

## Handoff Notes

> Read this section if you are the next agent picking up this work.

{handoff_notes}

## Context Pointers

```
CONTEXT.md     → domain glossary (read before grilling or implementing)
docs/adr/      → architectural decisions (do not re-litigate)
memory/mistakes.md → gate failures + lessons (read before implementing)
skills/SKILL.md → skill router (load the right skill for your task)
```

## Pipeline State

```
Last pipeline : #{pipeline_number}
Implement     : {implement_status}
Verify        : {verify_status}
Review        : {review_status}
SHA           : {sha}
```
"""


class SessionLog:
    def __init__(self, session_id: str, agent_tool: str = "claude-code"):
        self.session_id = session_id
        self.agent_tool = agent_tool
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.project = project_name()  # stable across worktrees (e.g. always "techne")
        self.task = ""
        self.status = "IN_PROGRESS"
        self.what_done: list[str] = []
        self.files_changed: list[str] = []
        self.decisions: list[str] = []
        self.mistakes: list[str] = []
        self.open_questions: list[str] = []
        self.handoff_notes: list[str] = []
        self.eval_score = 0
        self.eval_grade = "PENDING"
        self.eval_summary = ""
        self.pipeline_number = 0
        self.implement_status = "PENDING"
        self.verify_status = "PENDING"
        self.review_status = "PENDING"
        self.sha = "none"

    def set_task(self, task: str) -> "SessionLog":
        self.task = task
        return self

    def set_pipeline_result(
        self,
        pipeline_number: int,
        implement: str,
        verify: str,
        review: str,
        sha: str,
    ) -> "SessionLog":
        self.pipeline_number = pipeline_number
        self.implement_status = implement
        self.verify_status = verify
        self.review_status = review
        self.sha = sha
        self.status = "COMPLETE" if all(
            s.startswith("PASS") for s in [implement, verify, review]
        ) else "PARTIAL"
        return self

    def set_eval(self, score: int, grade: str, summary: str) -> "SessionLog":
        self.eval_score = score
        self.eval_grade = grade
        self.eval_summary = summary
        return self

    def add_done(self, item: str) -> "SessionLog":
        self.what_done.append(f"- {item}")
        return self

    def add_file(self, path: str, change: str = "modified") -> "SessionLog":
        self.files_changed.append(f"- `{path}` ({change})")
        return self

    def add_decision(self, decision: str, adr: str = "") -> "SessionLog":
        suffix = f" → see {adr}" if adr else ""
        self.decisions.append(f"- {decision}{suffix}")
        return self

    def add_mistake(self, gate: str, lesson: str) -> "SessionLog":
        self.mistakes.append(f"- `{gate}`: {lesson}")
        return self

    def add_question(self, question: str) -> "SessionLog":
        self.open_questions.append(f"- {question}")
        return self

    def add_handoff(self, note: str) -> "SessionLog":
        self.handoff_notes.append(f"- {note}")
        return self

    def _fmt(self, items: list[str], empty: str = "(none)") -> str:
        return "\n".join(items) if items else empty

    def render(self) -> str:
        return SESSION_TEMPLATE.format(
            session_id=self.session_id,
            timestamp=self.timestamp,
            agent_tool=self.agent_tool,
            project=self.project,
            status=self.status,
            eval_score=self.eval_score,
            task=self.task or "(no task set)",
            what_done=self._fmt(self.what_done),
            files_changed=self._fmt(self.files_changed),
            decisions=self._fmt(self.decisions),
            mistakes=self._fmt(self.mistakes),
            eval_grade=self.eval_grade,
            eval_summary=self.eval_summary or "(pending)",
            open_questions=self._fmt(self.open_questions),
            handoff_notes=self._fmt(self.handoff_notes, "(clean handoff — no open items)"),
            pipeline_number=self.pipeline_number,
            implement_status=self.implement_status,
            verify_status=self.verify_status,
            review_status=self.review_status,
            sha=self.sha,
        )

    def save(self) -> Path:
        """Write SESSION.md (current) and archive a timestamped copy."""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

        content = self.render()

        # Overwrite current session
        SESSION_FILE.write_text(content, encoding="utf-8")

        # Archive timestamped copy
        slug = self.task[:40].lower().replace(" ", "-").replace("/", "-") if self.task else "session"
        archive_name = f"{self.session_id}-{slug}.md"
        archive_path = SESSIONS_DIR / archive_name
        archive_path.write_text(content, encoding="utf-8")

        return SESSION_FILE


def load_current_session() -> str:
    """Return current SESSION.md content for cold-read by any agent."""
    if not SESSION_FILE.exists():
        return "(no session log found — start fresh)"
    return SESSION_FILE.read_text(encoding="utf-8")


def list_sessions() -> list[str]:
    """List archived session files, newest first."""
    if not SESSIONS_DIR.exists():
        return []
    return sorted(
        [f.name for f in SESSIONS_DIR.glob("*.md")],
        reverse=True,
    )


def new_session(agent_tool: str = "claude-code") -> SessionLog:
    """Create a new SessionLog with a fresh session ID."""
    session_id = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    return SessionLog(session_id=session_id, agent_tool=agent_tool)
