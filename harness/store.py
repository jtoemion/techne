"""
store.py — service layer: memory/ persistence mechanics.

Domain modules (checkpoint, evaluator, ...) own *what* their state means and
*when* it changes. This service owns the reusable *how* of reading and writing
JSON to disk reliably: existence handling, decode-error fallback, parent-dir
creation, and consistent encoding/formatting.

Composable capability blocks, explicit inputs, structured returns, no hidden
global state — callers pass the path and choose their own default.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
MEMORY_DIR = ROOT / "memory"


def read_json(path: "str | Path", default=None):
    """
    Read JSON from `path`. Return `default` if the file is missing or unparsable.

    The decode-error fallback makes corrupt/empty files non-fatal — callers get
    a clean default instead of an exception.
    """
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return default


def write_json(path: "str | Path", data) -> Path:
    """
    Write `data` as pretty JSON to `path`, creating parent dirs as needed.
    Returns the resolved Path written.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p
