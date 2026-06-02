"""
sha_gate.py — SHA-256 verification that the agent ran real tests.

The verifier agent must write full test stdout to test_output.txt.
This gate proves the file exists, is non-trivial, shows passing tests,
and logs the hash so repeated identical outputs are detectable.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from gates import GateViolation


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def gate_test_output(
    test_output_path: str = "test_output.txt",
    run_log_path: str = "memory/run_log.json",
) -> str:
    """
    Gate: verify the verifier agent ran real tests.

    Checks:
    1. File exists and is non-trivial (>50 chars)
    2. No FAILED / ERROR / 'error TS' lines present
    3. At least one pass indicator present
    4. Hashes and logs the output — identical hashes across runs = agent faking

    Returns the SHA-256 hex digest on success.
    """
    if not os.path.exists(test_output_path):
        raise GateViolation(
            "SHA GATE FAIL: test_output.txt is missing — "
            "verifier agent did not run tests"
        )

    content = open(test_output_path, encoding="utf-8", errors="replace").read()

    if len(content.strip()) < 50:
        raise GateViolation(
            f"SHA GATE FAIL: test_output.txt is too short ({len(content.strip())} chars) — "
            "likely faked or empty"
        )

    lower = content.lower()

    failure_patterns = ["npm err!", "error ts", "✗ failed", " failed "]
    for pat in failure_patterns:
        if pat in lower:
            preview = content[:600].replace("\n", "↵ ")
            raise GateViolation(
                f"SHA GATE FAIL: failure pattern '{pat}' found in test output.\n"
                f"Preview: {preview}"
            )

    pass_patterns = ["compiled successfully", "no issues found", "✓", "passed", " 0 errors"]
    if not any(p in lower for p in pass_patterns):
        raise GateViolation(
            "SHA GATE FAIL: no pass indicator found in test_output.txt. "
            f"Expected one of: {pass_patterns}"
        )

    file_hash = sha256_file(test_output_path)

    # Load or init log
    log: list = []
    if os.path.exists(run_log_path):
        try:
            log = json.load(open(run_log_path, encoding="utf-8"))
        except json.JSONDecodeError:
            log = []

    # Warn if hash is identical to the previous run
    if log and log[-1].get("test_output_hash") == file_hash:
        print(
            f"[SHA GATE] ⚠ Hash identical to previous run ({file_hash[:16]}...) — "
            "verify the agent is not reusing cached output"
        )

    log.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "test_output_hash": file_hash,
            "status": "PASSED",
        }
    )

    os.makedirs(os.path.dirname(run_log_path), exist_ok=True)
    json.dump(log, open(run_log_path, "w", encoding="utf-8"), indent=2)

    print(f"[SHA GATE] ✓ passed — hash: {file_hash[:16]}...")
    return file_hash
