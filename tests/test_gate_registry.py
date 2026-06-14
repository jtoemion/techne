"""Tests for the gate registry system."""
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'harness'))

from gate_registry import GateRegistry, GateMeta, _parse_yaml_simple
from gates import GateViolation


def test_register_and_run():
    """Registered gate runs when run_all() is called."""
    r = GateRegistry()
    calls = []
    def my_gate(diff):
        calls.append(diff)
    r.register("test/call-tracker", my_gate, stack="test")
    r.run_all("some diff")
    assert calls == ["some diff"], f"Gate should have been called, got {calls}"


def test_disable_skips_gate():
    """Disabled gates are skipped."""
    r = GateRegistry()
    calls = []
    r.register("test/disabled", lambda d: calls.append(1), enabled=False)
    r.run_all("diff")
    assert calls == [], "Disabled gate should not run"


def test_stack_filter():
    """stacks= param filters which gates run."""
    r = GateRegistry()
    ran = []
    r.register("a", lambda d: ran.append("a"), stack="nextjs")
    r.register("b", lambda d: ran.append("b"), stack="general")
    r.run_all("diff", stacks=["general"])
    assert ran == ["b"], f"Only general stack should run, got {ran}"


def test_hard_gate_raises():
    """Hard gate raises GateViolation, halting the run."""
    r = GateRegistry()
    def bad_gate(diff):
        raise GateViolation("test violation")
    r.register("test/fail", bad_gate, category="hard")
    try:
        r.run_all("diff")
        assert False, "Should have raised"
    except GateViolation as e:
        assert "test violation" in str(e)


def test_soft_gate_does_not_raise():
    """Soft gate catches violation but does not halt."""
    r = GateRegistry()
    ran = []
    def soft_fail(diff):
        raise GateViolation("soft")
    def second(diff):
        ran.append("second")
    r.register("test/soft", soft_fail, category="soft")
    r.register("test/after", second)
    r.run_all("diff")
    assert ran == ["second"], "Soft gate should not halt execution"


def test_pre_post_hooks():
    """Pre and post hooks fire around each gate."""
    r = GateRegistry()
    events = []
    def pre(diff, meta):
        events.append(f"pre:{meta.name}")
    def post(diff, meta, exc):
        events.append(f"post:{meta.name}:{'ok' if exc is None else 'fail'}")
    r.add_pre_hook(pre)
    r.add_post_hook(post)
    r.register("test/g1", lambda d: None)
    r.run_all("diff")
    assert events == ["pre:test/g1", "post:test/g1:ok"], f"Hook events: {events}"


def test_post_hook_sees_exception():
    """Post hook receives the exception from a failing hard gate."""
    r = GateRegistry()
    seen_exc = []
    def post(diff, meta, exc):
        seen_exc.append(exc)
    r.add_post_hook(post)
    def fail(diff):
        raise GateViolation("boom")
    r.register("test/fail", fail, category="hard")
    try:
        r.run_all("diff")
    except GateViolation:
        pass
    assert len(seen_exc) == 1
    assert isinstance(seen_exc[0], GateViolation)


def test_unregister():
    """Unregister removes the gate."""
    r = GateRegistry()
    r.register("test/tmp", lambda d: None)
    assert r.get("test/tmp") is not None
    r.unregister("test/tmp")
    assert r.get("test/tmp") is None


def test_list_gates():
    """list_gates returns correct filters."""
    r = GateRegistry()
    r.register("a", lambda d: None, stack="nextjs")
    r.register("b", lambda d: None, stack="general", enabled=False)
    r.register("c", lambda d: None, stack="general")
    assert len(r.list_gates()) == 2  # excludes disabled
    assert len(r.list_gates(stack="general")) == 1
    assert len(r.list_gates(enabled_only=False)) == 3


def test_enable_disable():
    """Enable/disable toggles gate state."""
    r = GateRegistry()
    r.register("test/toggle", lambda d: None, enabled=False)
    assert r.get("test/toggle").enabled is False
    r.enable("test/toggle")
    assert r.get("test/toggle").enabled is True
    r.disable("test/toggle")
    assert r.get("test/toggle").enabled is False


def test_overwrite_register():
    """Re-registering with same name overwrites the gate."""
    r = GateRegistry()
    r.register("test/ov", lambda d: "first")
    r.register("test/ov", lambda d: "second")
    assert r.get("test/ov").fn("x") == "second"


def test_load_config_disables_stacks():
    """load_config with active_stacks disables gates outside those stacks."""
    r = GateRegistry()
    r.register("a", lambda d: None, stack="nextjs")
    r.register("b", lambda d: None, stack="general")
    r.register("c", lambda d: None, stack="typescript")
    cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    cfg.write("active_stacks:\n  - general\n")
    cfg.close()
    r.load_config(config_path=Path(cfg.name))
    os.unlink(cfg.name)
    enabled = [g.name for g in r.list_gates()]
    assert enabled == ["b"], f"Only 'b' (general) should be enabled, got {enabled}"


def test_load_config_disables_specific_gates():
    """load_config with disabled_gates turns off specific gates."""
    r = GateRegistry()
    r.register("a", lambda d: None, stack="general")
    r.register("b", lambda d: None, stack="general")
    cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    cfg.write('disabled_gates:\n  - "b"\n')
    cfg.close()
    r.load_config(config_path=Path(cfg.name))
    os.unlink(cfg.name)
    enabled = [g.name for g in r.list_gates()]
    assert enabled == ["a"], f"Only 'a' should be enabled, got {enabled}"


def test_parse_yaml_simple():
    """Minimal YAML parser handles our config format."""
    text = '''version: "1.0"
active_stacks:
  - general
  - nextjs
disabled_gates:
  - "test/gate"
'''
    result = _parse_yaml_simple(text)
    assert result["version"] == "1.0"
    assert result["active_stacks"] == ["general", "nextjs"]
    assert result["disabled_gates"] == ["test/gate"]


def test_config_before_register():
    """Config loaded before register() still applies to new gates."""
    r = GateRegistry()
    # Load config first — only "general" active
    cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    cfg.write("active_stacks:\n  - general\n")
    cfg.close()
    r.load_config(config_path=Path(cfg.name))
    os.unlink(cfg.name)
    # Register gates AFTER config load
    r.register("a", lambda d: None, stack="nextjs")
    r.register("b", lambda d: None, stack="general")
    enabled = [g.name for g in r.list_gates()]
    assert enabled == ["b"], f"Config should retroactively disable, got {enabled}"


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL {name}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("All tests passed.")
