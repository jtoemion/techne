"""
_mem_guard.py — keep integration tests from dirtying the committed memory/ ledgers.

Tests that drive the REAL pipeline (conductor, synthetic, etc.) legitimately write to
memory/reward.md, mistakes.md, eval_history.json, sessions/, … . That left the working
tree dirty after every suite run. Importing this module snapshots those files at import
time and restores them via atexit — so the run's writes happen normally (assertions see
them) but the tree is clean afterward. Side-effect on import, by design:

    sys.path.insert(0, str(TESTS_DIR)); import _mem_guard  # noqa
"""

import atexit
from pathlib import Path

MEM = Path(__file__).resolve().parent.parent / ".techne" / "memory"
SESSIONS = MEM / "sessions"

# Files an integration run may append to / overwrite.
_GUARDED = [
    "reward.md", "mistakes.md", "ledger.md", "eval_history.json", "run_log.json",
    "harness-state.json", "SESSION.md", "latest_eval.txt", "retro_proposals.md",
    "test_output.txt", "implementer_output.txt",
]

# Snapshot BYTES, not text: write_text on Windows rewrites \n as \r\n, which would
# flip the repo's LF-normalized files to CRLF and show as "modified". Bytes round-trip
# is exact, so a clean tree stays clean.
_snapshot = {
    name: ((MEM / name).read_bytes() if (MEM / name).exists() else None)
    for name in _GUARDED
}
_sessions_before = {p.name for p in SESSIONS.glob("*.md")} if SESSIONS.exists() else set()


def _restore() -> None:
    for name, content in _snapshot.items():
        p = MEM / name
        if content is None:
            p.unlink(missing_ok=True)          # file didn't exist before → remove it
        else:
            p.write_bytes(content)
    if SESSIONS.exists():
        for p in SESSIONS.glob("*.md"):
            if p.name not in _sessions_before:  # remove session logs this run created
                p.unlink(missing_ok=True)


atexit.register(_restore)
