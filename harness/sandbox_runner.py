"""
sandbox_runner.py — W6 throwaway-worktree sandbox for VERIFY (GRAND-PLAN-FINAL §6).

The driver's VERIFY phase runs a real test suite. Without isolation, every IMPLEMENT
attempt mutates the live tree — a failure leaves garbage and may corrupt subsequent runs.
This module wraps VERIFY in a throwaway git worktree: apply the diff there, run tests
there, discard. The live tree is never touched.

Contract:
  run_in_worktree(patch, test_cmd) → SandboxResult
    Apply `patch` to a fresh checkout at HEAD, run `test_cmd`, remove the worktree.
    Returns immediately; caller gets pass/fail + output without touching the main tree.

  sandbox_test_runner(test_cmd, get_patch) → TestFn
    A drop-in replacement for model_backends.command_test_runner that runs VERIFY in
    a throwaway worktree. get_patch() is called at VERIFY time to produce the unified
    diff to test. Raises SandboxHaltError if the patch cannot be applied — the driver
    should treat this as HALT (unapplyable patch is a hard failure, not a retry).

Microsandbox (WSL2 microVM) upgrade path:
  run_in_microsandbox() is provided for VM-level isolation on Linux / WSL2+KVM.
  It shells into WSL2 and runs `msb exec` with the test command.
  Falls back to worktree if microsandbox is unavailable.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent   # techne/


class SandboxHaltError(RuntimeError):
    """Raised when a diff cannot be applied — the caller should HALT, not retry."""


@dataclass
class SandboxResult:
    passed: bool
    patch_applied: bool
    stdout: str
    exit_code: int
    worktree_path: Optional[str] = None


# ── git worktree isolation ────────────────────────────────────────────────────

def run_in_worktree(
    patch: str,
    test_cmd: str,
    *,
    base_ref: str = "HEAD",
    cwd: Optional[Path] = None,
    timeout: int = 300,
) -> SandboxResult:
    """Apply *patch* to a throwaway git worktree and run *test_cmd*.

    The worktree is created at `base_ref` (default: HEAD), the patch applied
    via `git apply`, the suite run, and the worktree removed — regardless of
    outcome. The main working tree is never modified.

    Raises SandboxHaltError if `git apply` fails (unapplyable diff = HALT).
    """
    repo_root = cwd or _ROOT
    wt_dir = Path(tempfile.gettempdir()) / f"techne-sandbox-{uuid.uuid4().hex[:8]}"

    try:
        # Create a clean worktree at base_ref.
        _git(["worktree", "add", "--detach", str(wt_dir), base_ref], cwd=repo_root)

        if patch.strip():
            # Validate the patch applies before trying.
            check = _git(
                ["apply", "--check", "--whitespace=nowarn", "-"],
                cwd=wt_dir,
                input=patch,
                check=False,
            )
            if check.returncode != 0:
                raise SandboxHaltError(
                    f"patch does not apply cleanly to {base_ref}:\n{check.stderr}"
                )
            # Apply the patch.
            _git(
                ["apply", "--whitespace=nowarn", "-"],
                cwd=wt_dir,
                input=patch,
            )

        # Run the test suite inside the worktree.
        proc = subprocess.run(
            test_cmd,
            cwd=wt_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        passed = proc.returncode == 0
        return SandboxResult(
            passed=passed,
            patch_applied=bool(patch.strip()),
            stdout=combined,
            exit_code=proc.returncode,
            worktree_path=str(wt_dir),
        )

    finally:
        # Always remove the worktree — ignore errors (dir may not exist if add failed).
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_dir)],
            cwd=repo_root,
            capture_output=True,
        )


def _git(args: list[str], *, cwd: Path, input: Optional[str] = None,
         check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
        check=check,
    )


# ── microsandbox (WSL2 microVM) isolation — upgrade path ─────────────────────

def _msb_available() -> bool:
    """Return True if msb is accessible in WSL2 on Windows, or natively on Linux."""
    if sys.platform == "linux":
        return subprocess.run(["which", "msb"], capture_output=True).returncode == 0
    if sys.platform == "win32":
        r = subprocess.run(
            ["wsl.exe", "bash", "-c", "which msb"],
            capture_output=True,
            env={**__import__("os").environ, "MSYS_NO_PATHCONV": "1"},
        )
        return r.returncode == 0
    return False


def run_in_microsandbox(
    patch: str,
    test_cmd: str,
    *,
    base_ref: str = "HEAD",
    cwd: Optional[Path] = None,
    timeout: int = 300,
) -> SandboxResult:
    """Run tests inside a microsandbox microVM (Linux+KVM / WSL2).

    Falls back to run_in_worktree if microsandbox is unavailable.
    The repo is cloned into the sandbox, the patch applied, tests run.
    """
    if not _msb_available():
        return run_in_worktree(patch, test_cmd, base_ref=base_ref, cwd=cwd, timeout=timeout)

    repo_root = cwd or _ROOT

    # Build a shell script that clones the repo, applies the patch, and runs tests.
    patch_escaped = patch.replace("'", "'\\''")
    script = f"""
set -e
TMPDIR=$(mktemp -d)
git clone --depth=1 --branch=HEAD file://{repo_root} "$TMPDIR" 2>/dev/null || \
  git clone --depth=1 file://{repo_root} "$TMPDIR"
cd "$TMPDIR"
git checkout {base_ref} -- . 2>/dev/null || true
if [ -n '{patch_escaped}' ]; then
  printf '%s' '{patch_escaped}' | git apply --whitespace=nowarn - || exit 2
fi
{test_cmd}
"""

    if sys.platform == "win32":
        proc = subprocess.run(
            ["wsl.exe", "bash", "-c", f"msb exec -- bash -c '{script}'"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**__import__("os").environ, "MSYS_NO_PATHCONV": "1"},
        )
    else:
        proc = subprocess.run(
            ["msb", "exec", "--", "bash", "-c", script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    combined = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 2:
        raise SandboxHaltError(f"patch did not apply in microsandbox:\n{combined}")

    return SandboxResult(
        passed=proc.returncode == 0,
        patch_applied=bool(patch.strip()),
        stdout=combined,
        exit_code=proc.returncode,
    )


# ── TestFn factory (drop-in for command_test_runner) ─────────────────────────

def sandbox_test_runner(
    test_cmd: str,
    get_patch: Callable[[], str],
    *,
    strategy: str = "worktree",
    cwd: Optional[Path] = None,
    timeout: int = 300,
) -> Callable[[], str]:
    """Return a TestFn that runs *test_cmd* in a throwaway worktree.

    Drop-in replacement for model_backends.command_test_runner.

    Args:
        test_cmd:  The real test command (e.g. "pytest -q").
        get_patch: Called at VERIFY time; must return a unified-diff string of the
                   changes to test. Typically ``lambda: _git_diff_head()``.
        strategy:  "worktree" (default) or "microsandbox".
        cwd:       Git repo root (default: techne/).
        timeout:   Max seconds for the test run.

    The returned TestFn raises SandboxHaltError if the patch cannot be applied.
    Callers (driver.py) should treat this as a hard HALT.
    """
    _runner = run_in_microsandbox if strategy == "microsandbox" else run_in_worktree

    def _run() -> str:
        patch = get_patch()
        result = _runner(patch, test_cmd, cwd=cwd, timeout=timeout)
        return result.stdout

    return _run


def git_diff_head(cwd: Optional[Path] = None) -> str:
    """Return a unified diff of all changes in the working tree vs HEAD."""
    repo_root = cwd or _ROOT
    proc = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return proc.stdout or ""


# ── CLI for manual testing ────────────────────────────────────────────────────

def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Run tests in a throwaway sandbox.")
    ap.add_argument("--test-cmd", default="pytest -q", help="Test command to run")
    ap.add_argument("--patch", default=None, help="Path to .patch file (default: git diff HEAD)")
    ap.add_argument("--strategy", choices=["worktree", "microsandbox"], default="worktree")
    ap.add_argument("--base-ref", default="HEAD")
    args = ap.parse_args()

    patch = ""
    if args.patch:
        patch = Path(args.patch).read_text(encoding="utf-8")
    else:
        patch = git_diff_head()

    print(f"[sandbox] strategy={args.strategy} base={args.base_ref}")
    print(f"[sandbox] patch: {len(patch)} chars, test_cmd: {args.test_cmd!r}")

    try:
        if args.strategy == "microsandbox":
            result = run_in_microsandbox(patch, args.test_cmd, base_ref=args.base_ref)
        else:
            result = run_in_worktree(patch, args.test_cmd, base_ref=args.base_ref)
    except SandboxHaltError as e:
        print(f"[sandbox] HALT: {e}")
        return 3

    print(result.stdout)
    print(f"[sandbox] passed={result.passed} exit_code={result.exit_code}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
