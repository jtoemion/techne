# Orchestrator RECALL Workshop Contract

This document captures the structured output contract and workshop retrieval pattern integrated into the orchestrator loop in the TECHNE improvement handoff.

## Structured Output Contract

Every RECALL phase submission (model output) must contain these prefix-prefixed lines:

```
HONCHO_CONTEXT: <durable context from Honcho>
WORKSHOP_CONTEXT: <comma-separated .techne/context docs used, or "none">
WORKSHOP_FILES: <comma-separated files surfaced by retrieval, or "none">
LESSONS: <relevant lessons/mistakes/decisions, or "none">
FOCUS: <2-4 lines on what IMPLEMENT should touch/avoid>
```

### Validation rules (in `_submit_recall`)

| Check | Applies to | What happens |
|-------|-----------|--------------|
| Result length < 20 chars | All modes | RETRY with "no usable context" |
| Missing `HONCHO_CONTEXT:` line | All modes | RETRY — must include structured proof |
| Missing `WORKSHOP_CONTEXT:` line | Full-mode only | RETRY — fast-mode skips this check |

### IMPLEMENT gate enforcement (in `_submit_implement`)

For full-mode tasks, IMPLEMENT checks the history for the most recent RECALL event and validates its `findings` contain `workshop_context:`. If missing, RETRY with "latest RECALL artifact does not reference WORKSHOP_CONTEXT."

Fast-mode tasks skip this check entirely.

## Agent Mapping

The `_read_agent_body()` method maps phases to agent definition files:

```python
agent_map = {
    "RECALL": "recaller",       # agents/recaller.md
    "IMPLEMENT": "implementer",
    "CONTEXT_GUARD": "context-guard",
    "CRITIQUE": "critique",
    "REVIEW": "reviewer",
    "VERIFY": "verifier",
    "CONCLUDE": "concluder",    # agents/concluder.md
    "DEBUG": "debugger",
}
```

Previously RECALL fell through to `phase.lower()` (→ `recall` → file-not-found fallback). Now both RECALL and CONCLUDE have explicit entries.

## Workshop Retrieval Packet (`_build_workshop_recall_lines`)

Called from `_build_user_context()` during RECALL prompt assembly. Flow:

1. Calls `workshop.find_workshop_paths(Path.cwd())` to locate `.techne/config.yaml`
2. If no workshop found → emits `WORKSHOP_STATUS: no .techne/config.yaml found`
3. If workshop found → runs `.techne/scripts/context_search.py <query> --json` as subprocess
4. Parses JSON response, extracting up to:
   - 5 context docs (`context_docs[].path`)
   - 8 files (`files[].path`)
   - 5 subsystems (`subsystems[].name`)
   - 2 entries per memory bucket (lessons, mistakes, decisions)

Output lines added to the RECALL prompt:
```
WORKSHOP_STATUS: ok | retrieval failed: <reason> | missing script <path>
WORKSHOP_QUERY: <query string>
LIKELY_SUBSYSTEMS: <comma-separated>
CONTEXT_DOC_CANDIDATES: <comma-separated>
FILE_CANDIDATES: <comma-separated>
MEMORY_CANDIDATES: <pipe-separated>
```

### Error handling

| Failure mode | Behavior |
|-------------|----------|
| No `find_workshop_paths()` (import error) | Emits WORKSHOP_STATUS with exception message |
| Missing `.techne/config.yaml` | WORKSHOP_STATUS: no .techne/config.yaml found |
| Missing `context_search.py` script | WORKSHOP_STATUS: missing script |
| context_search.py returns non-zero | WORKSHOP_STATUS: retrieval failed with stderr |
| context_search.py returns invalid JSON | JSON parse exception caught, WORKSHOP_STATUS emitted |
| No matching results | All candidate lists show "none" |

All errors are non-fatal — the RECALL prompt is still assembled, just without workshop candidates.

## Agent Files Created

### recaller.md
- Structured output format with 5 required lines
- "What IMPLEMENT Checks" section documenting the gate
- Hard constraint: must use actual Honcho context, not placeholders

### concluder.md
- Structured output format: HONCHO/DOCS/CONTEXT lines
- SHA requirement for CONTEXT updates
- Action/reason pairs for each line

## Driver phase_mode Propagation

`run_plan()` in driver.py now passes these fields from dict specs to `create_task()`:
- `tags` → tag-based routing (e.g. `review-only` for fast-mode tasks)
- `phase_mode` → "full" (default, all 10 phases) or "fast" (skips RECALL+CONCLUDE)
- `discipline`, `priority`, `parent_id` → passthrough

Previously all dict specs only passed `title` and `description`, discarding other metadata.
