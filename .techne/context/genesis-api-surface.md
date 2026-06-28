---
name: genesis-api-surface
type: source-note
title: Auto-generated API surface
description: Public symbols from 85 Python modules
timestamp: 2026-06-28T21:31:29.808364+00:00
tags: [genesis, auto]
---

# Auto-generated API Surface (GENESIS)

Generated from 85 Python source modules.


## `docs/plans/receptionist_enforcer.py`

- `TicketTransition`
- `ReceptionistEnforcer`

## `harness/_loop_types.py`

- `LoopAction`
- `LoopOutcome`

## `harness/_orchestrator_context.py`

- `set_task_type`
- `set_variant`
- `get_best_variant`
- `post_run_evolve`
- `rl_dashboard`

## `harness/_orchestrator_helpers.py`

- `get_eval`

## `harness/_orchestrator_retry.py`

- `summarize_incomplete`

## `harness/apply_retro.py`

- `parse_proposals`
- `apply_add`
- `apply_delete`
- `apply_resolve`
- `mark_applied`
- `check_regressions`
- `format_regressions`
- `review_and_apply`
- `has_pending_proposals`
- `auto_apply_pending`

## `harness/checkpoint.py`

- `read_state`
- `write_state`
- `init_state`
- `log_gate_pass`
- `log_gate_fail`
- `mark_honcho_concluded`
- `check_honcho_logged`
- `clear_honcho_flag`
- `mark_verified`
- `check_verification`
- `increment_pipeline_run`
- `get_summary`

## `harness/classify.py`

- `classify_task_group`

## `harness/context_build.py`

- `build_context`
- `ensure_context`
- `conclude_context`

## `harness/context_preflight.py`

- `ensure_context_dir`
- `compute_context_hash`
- `context_status`
- `write_context_hash`
- `select_context_pack`
- `format_preflight_prompt`
- `extract_changed_files_from_report`

## `harness/diff_parser.py`

- `FileSummary`
- `DiffSummary`
- `parse_diff`

## `harness/driver.py`

- `TaskRun`
- `PlanResult`
- `run_plan`

## `harness/enforcement.py`

- `GateResult`
- `ScopeResult`
- `VerifyResult`
- `build_registry`
- `run_gates`
- `measure_scope`
- `verify_tests`

## `harness/evaluator.py`

- `RegressionInfo`
- `EvalReport`
- `load_eval_history`
- `save_eval`
- `evaluate_pipeline_run`

## `harness/gate_evolution.py`

- `CandidateGate`
- `TestResult`
- `GateProposal`
- `GateEvolution`

## `harness/gate_registry.py`

- `GateMeta`
- `GateRegistry`

## `harness/gates.py`

- `GateViolation`
- `gate_no_redirect_outside_middleware`
- `gate_no_router_import`
- `gate_no_gSSP`
- `gate_no_ts_ignore`
- `gate_no_console_log`
- `run_all_gates`
- `run_all_gates_report`
- `format_gate_report`

## `harness/grpo.py`

- `propose_grpo_edits`
- `propose_skill_edits`
- `propose_framework_edits`

## `harness/intent_reasoner.py`

- `IntentVerdict`
- `build_semantic_prompt`
- `parse_semantic_response`
- `reason_about_intent`
- `verdict_to_gate`

## `harness/ledger.py`

- `log_entry`
- `log_decision`
- `log_lesson`
- `log_discipline`
- `check_relevant`
- `count_active`
- `count_by_kind`
- `validate`

## `harness/measure.py`

- `extract_changed_files`
- `count_added_lines`
- `count_removed_lines`
- `extract_task_keywords`
- `measure_diff_focus`
- `measure_scope_creep`
- `measure_intent`
- `gate_intent`
- `full_intent_check`
- `run_measurements`

## `harness/mistakes.py`

- `log_mistake`
- `check_relevant`
- `mark_resolved`
- `count_active`
- `count_by_skill`

## `harness/model_backends.py`

- `claude_cli_model`
- `anthropic_model`
- `openai_model`
- `gemini_model`
- `minimax_model`
- `PhaseRouter`
- `default_provider`
- `providers`
- `make_model`
- `make_phase_router`
- `command_test_runner`

## `harness/orchestrator_loop.py`

- `OrchestratorLoop`

## `harness/phase_skills.py`

- `parse_retro_markers`

## `harness/pipeline_enforcer.py`

- `get_analysis_threshold`
- `get_mode_overrides`
- `analyze_override_patterns`
- `suggest_classifier_updates`
- `get_classifier_insights`
- `get_cost_estimate`
- `classify_phase_mode`
- `detect_sensitive_change`
- `validate_mode_fit`
- `validate_micro_mode`
- `PhaseTransition`
- `PipelineEnforcer`
- `get_phase_prompt`

## `harness/plugins/builtin_gates.py`

- `register`

## `harness/plugins/phase_guard.py`

- `check_write_allowed`
- `get_blocked_log`
- `log_blocked`

## `harness/plugins/pipeline_hooks.py`

- `install_pipeline_hooks`
- `set_task_context`

## `harness/plugins/security_gates.py`

- `register`

## `harness/prompt_evolution.py`

- `VariantStats`
- `Proposal`
- `PromptEvolution`

## `harness/reward.py`

- `log_reward`
- `log_clean`
- `log_solved`
- `count_by_skill`
- `points_by_skill`
- `total_points`
- `net_by_skill`
- `check_relevant`
- `validate`

## `harness/reward_log.py`

- `Reward`
- `RewardLog`

## `harness/router.py`

- `route`
- `get_always_loaded`
- `get_stack_loaded`
- `resolve_stack_skills`
- `stack_gated_paths`
- `get_common_loaded`
- `route_with_explanation`

## `harness/session.py`

- `project_name`
- `SessionLog`
- `load_current_session`
- `list_sessions`
- `new_session`

## `harness/sha_gate.py`

- `sha256_file`
- `gate_test_output`

## `harness/stack_detect.py`

- `detect_stack`

## `harness/store.py`

- `state_dir`
- `read_json`
- `write_json`

## `harness/synthetic_bootstrap.py`

- `SyntheticScore`
- `SyntheticBootstrap`

## `harness/task_db.py`

- `Task`
- `TaskEvent`
- `TaskDB`