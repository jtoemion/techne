"""
test_model_backends.py — the real edges of the driver, tested WITHOUT a real model.

The model adapters shell out / call an SDK; we verify their WIRING (command shape,
stdin prompt, error handling) with a fake subprocess — no tokens, no network, no auth.
command_test_runner is exercised against a real but harmless local command.

NOTE: model_backends references the shared `subprocess`/`shutil` modules, so patching
must save the TRUE originals up front and restore them (mutating the module in place and
re-reading it would leak the fake into every other test). _patch() handles that.

Run from tests/:  python test_model_backends.py
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT / "harness"))

import model_backends as mb

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []

# True originals, captured once before any test can mutate the shared modules.
_ORIG_RUN = subprocess.run
_ORIG_WHICH = shutil.which


def check(label, cond):
    results.append(bool(cond))
    print(f"  {PASS if cond else FAIL} {label}")


@contextlib.contextmanager
def _patch(*, run=None, which=None):
    """Temporarily patch subprocess.run / shutil.which, always restoring originals."""
    try:
        if run is not None:
            subprocess.run = run
        if which is not None:
            shutil.which = which
        yield
    finally:
        subprocess.run = _ORIG_RUN
        shutil.which = _ORIG_WHICH


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_claude_cli_builds_command_and_passes_prompt_on_stdin():
    print("\n[claude_cli_model — command shape + stdin prompt]")
    captured = {}

    def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None):
        captured["cmd"] = cmd
        captured["input"] = input
        return _FakeProc(stdout="MODEL OUTPUT\n")

    with _patch(run=fake_run, which=lambda b: "/usr/bin/claude"):
        model = mb.claude_cli_model()
        out = model("SYS", "USER", "implement")
    check("returns stdout (stripped)", out == "MODEL OUTPUT")
    check("invokes the print flag (-p)", "-p" in captured["cmd"])
    check("prompt carries system + user on stdin",
          "SYS" in captured["input"] and "USER" in captured["input"])


def test_claude_cli_raises_on_nonzero():
    print("\n[claude_cli_model — non-zero exit raises]")
    with _patch(run=lambda *a, **k: _FakeProc(stderr="boom", returncode=2),
                which=lambda b: "/usr/bin/claude"):
        model = mb.claude_cli_model()
        raised = False
        try:
            model("S", "U", "review")
        except RuntimeError as e:
            raised = "boom" in str(e)
    check("RuntimeError surfaced with stderr", raised)


def test_claude_cli_missing_binary_raises():
    print("\n[claude_cli_model — missing binary is a clear error]")
    with _patch(which=lambda b: None):
        raised = False
        try:
            mb.claude_cli_model(binary="definitely-not-claude")
        except RuntimeError as e:
            raised = "not found" in str(e)
    check("missing CLI → RuntimeError", raised)


def test_anthropic_missing_key_or_pkg_raises():
    print("\n[anthropic_model — fails clearly without key/package]")
    import os
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        raised = False
        try:
            mb.anthropic_model()
        except RuntimeError:
            raised = True          # either "pip install anthropic" or "ANTHROPIC_API_KEY"
        check("no key/package → RuntimeError (never a silent call)", raised)
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_make_model_dispatches_and_rejects_unknown():
    print("\n[make_model — registry dispatch + unknown provider]")
    import model_backends as _mb
    check("providers() lists all four",
          set(_mb.providers()) == {"claude-cli", "anthropic", "openai", "gemini"})
    raised = False
    try:
        _mb.make_model("not-a-provider")
    except RuntimeError as e:
        raised = "unknown provider" in str(e)
    check("unknown provider → RuntimeError", raised)


def test_make_model_filters_options_per_provider():
    print("\n[make_model — forwards only options a provider accepts]")
    # claude-cli takes no model/base_url; passing them must NOT crash (they're filtered).
    with _patch(which=lambda b: "/usr/bin/claude"):
        fn = mb.make_model("claude-cli", model="ignored", base_url="ignored")
    check("claude-cli built despite extra opts (filtered)", callable(fn))


def _provider_error(provider, **opts):
    """Build a provider and return the RuntimeError text (SDK/key missing in this env)."""
    try:
        mb.make_model(provider, **opts)
        return ""
    except RuntimeError as e:
        return str(e)


def test_openai_provider_fails_clearly_without_sdk_or_key():
    print("\n[openai — clear error without SDK/key, never a silent call]")
    err = _provider_error("openai", model="gpt-4o")
    check("openai surfaces a RuntimeError",
          ("openai" in err.lower()) or ("OPENAI_API_KEY" in err))


def test_gemini_provider_fails_clearly_without_sdk_or_key():
    print("\n[gemini — clear error without SDK/key]")
    err = _provider_error("gemini")
    check("gemini surfaces a RuntimeError",
          ("google-generativeai" in err) or ("GEMINI_API_KEY" in err))


def test_openai_base_url_is_accepted_for_compatibility():
    print("\n[openai — base_url option is accepted (OpenRouter/Groq/Ollama path)]")
    import inspect as _i
    params = _i.signature(mb.openai_model).parameters
    check("openai_model exposes base_url", "base_url" in params)
    check("openai_model exposes api_key_env (swap providers' keys)", "api_key_env" in params)


def test_command_test_runner_runs_real_command():
    print("\n[command_test_runner — runs a real command, returns its output]")
    run = mb.command_test_runner([sys.executable, "-c", "print('10 passed')"])
    out = run()
    check("captures real stdout", "10 passed" in out)
    run2 = mb.command_test_runner(f'{sys.executable} -c "print(123)"')  # string → shell=True
    check("string command form works", "123" in run2())


def test_patching_left_no_residue():
    print("\n[hygiene — module globals restored after patching]")
    check("subprocess.run restored", subprocess.run is _ORIG_RUN)
    check("shutil.which restored", shutil.which is _ORIG_WHICH)


if __name__ == "__main__":
    print("=" * 60)
    print("MODEL BACKENDS — adapter wiring (no real model calls)")
    print("=" * 60)
    test_claude_cli_builds_command_and_passes_prompt_on_stdin()
    test_claude_cli_raises_on_nonzero()
    test_claude_cli_missing_binary_raises()
    test_anthropic_missing_key_or_pkg_raises()
    test_make_model_dispatches_and_rejects_unknown()
    test_make_model_filters_options_per_provider()
    test_openai_provider_fails_clearly_without_sdk_or_key()
    test_gemini_provider_fails_clearly_without_sdk_or_key()
    test_openai_base_url_is_accepted_for_compatibility()
    test_command_test_runner_runs_real_command()
    test_patching_left_no_residue()
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed" + ("  -- all clear" if passed == total else f"  ({total-passed} FAILED)"))
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
