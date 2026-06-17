# Commands

## Validation

```bash
python -m py_compile harness/context_preflight.py harness/orchestrator_loop.py harness/pipeline_enforcer.py
python -X utf8 tests/test_context_amortization.py
python -X utf8 tests/test_adopted.py
python -X utf8 tests/test_harness.py
git diff --check
```

## Router/Evals

```bash
python tests/evals/run_evals.py --suite router
python tests/evals/run_evals.py
```

If router cases change intentionally, review `tests/evals/results/baseline.json`.
Do not overwrite baseline unless the new expected behavior should become the
regression target.

## Git

```bash
git status --short
git switch -c feature/<short-name>
git add <intended-files>
git commit -m "feat: add mandatory context preflight"
git push origin feature/<short-name>
```

Do not commit unrelated dirty files from worktrees, memory state, or eval result
artifacts.

## Skill Authoring

```bash
# Required reading before creating/modifying skills
skills/writing-skill.md
skills/writing-skill/template.md
skills/writing-skill/checklist.md
```

Use `write_file` for new in-repo skills. Use `patch` or `write_file` for edits.
Do not use `skill_manage(action='create')` for in-repo skills.

## Next Steps

```
- Need file ownership? → .techne/context/file_roles.md
- Need risk boundaries? → .techne/context/risk_boundaries.md
- Need Techne pack? → .techne/context/context_packs/techne.md