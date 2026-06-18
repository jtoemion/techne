# Tests — canonical runner

**`python -m pytest tests/ -q` is the source of truth.** Run it before trusting any
result. The eval suite is separate and complementary:
`python tests/evals/run_evals.py` (router/gates/intent scoring, must stay 75/75).

## Two run modes, one truth

Every test file works **both** ways now:

- **Under pytest** (canonical): all `test_*` functions are collected and graded.
- **As a script** (`python tests/test_x.py`): each file's `__main__` runs its own
  checks, or delegates to pytest. Useful for a quick single-file run.

## The masking trap this suite had (don't reintroduce it)

Many files record outcomes into a module-global `results` list via helpers like
`ok()/fail()` or `check(label, cond)` instead of `assert`. A bare `test_*` that only
records **never raises**, so pytest would mark it green even with recorded failures.

`conftest.py` closes this: after each test, it fails the test if it appended any
failure to `results`. So the record-and-continue style is safe — but **plain `assert`
is preferred for new tests** (it needs no helper and fails loudly on both runners).

If you add a script-style file, give it a `__main__` (delegate to pytest with
`raise SystemExit(pytest.main([__file__, "-q"]))`) and clean up any scratch files in a
`teardown_module` so pytest leaves no cruft.
