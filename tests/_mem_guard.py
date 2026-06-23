"""
_mem_guard.py — keep integration tests from dirtying committed .techne/ artifacts.

Tests that drive the REAL pipeline (conductor, synthetic, etc.) legitimately
write to .techne/memory/, .techne/reports/, .techne/logs/, etc. That left the
working tree dirty after every suite run. Importing this module snapshots those
files at import time and restores them via atexit — so the run's writes happen
normally (assertions see them) but the tree is clean afterward.

Side-effect on import, by design:

    sys.path.insert(0, str(TESTS_DIR)); import _mem_guard  # noqa
"""

import atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / ".techne" / "memory"
EVAL = ROOT / ".techne" / "reports" / "eval"
VERIFY = ROOT / ".techne" / "reports" / "verify"
LOGS = ROOT / ".techne" / "logs"
SESSIONS = MEM / "sessions"

# Files an integration run may append to / overwrite.
# Each entry: (relative_label, directory)
_GUARDED: list[tuple[str, Path]] = [
    ("reward.md", MEM),
    ("mistakes.md", MEM),
    ("ledger.md", MEM),
    ("harness-state.json", MEM),
    ("SESSION.md", MEM),
    ("retro_proposals.md", MEM),
    ("implementer_output.txt", MEM),
    ("eval_history.json", EVAL),
    ("latest_eval.txt", EVAL),
    ("test_output.txt", VERIFY),
    ("run_log.json", LOGS),
]

# Snapshot BYTES, not text: write_text on Windows rewrites \n as \r\n, which would
# flip the repo's LF-normalized files to CRLF and show as "modified". Bytes round-trip
# is exact, so a clean tree stays clean.
_snapshot = {}
for name, directory in _GUARDED:
    path = directory / name
    _snapshot[(name, directory)] = path.read_bytes() if path.exists() else None

_sessions_before = {p.name for p in SESSIONS.glob("*.md")} if SESSIONS.exists() else set()


def _restore() -> None:
    for (name, directory), content in _snapshot.items():
        p = directory / name
        if content is None:
            p.unlink(missing_ok=True)          # file didn't exist before → remove it
        else:
            p.write_bytes(content)
    if SESSIONS.exists():
        for p in SESSIONS.glob("*.md"):
            if p.name not in _sessions_before:  # remove session logs this run created
                p.unlink(missing_ok=True)


atexit.register(_restore)
