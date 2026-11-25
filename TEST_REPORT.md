# Test Report

Generated 2026-11-25 14:41 UTC. 92 tests run: 90 passed, 2 skipped, 0 failed, 0 errored.

All executed tests passed. Skipped tests (if any) are listed below with their specific reason, they are not counted as passing and should not be read as such.

## Skipped, with reasons

- `tests.test_github_pull.LiveIntegrationTests.test_live_dormant_repo_is_stale`: dormant-repo staleness check: GitHub API rate limit was exhausted during this attempt (0 remaining, confirmed immediately after). Not a code failure, an external quota state, and the equivalent logic path is covered deterministically by MockedNegativeCaseTests above.
- `tests.test_github_pull.LiveIntegrationTests.test_live_repo_with_no_ci_configured`: no-CI-configured check: GitHub API rate limit was exhausted during this attempt (0 remaining, confirmed immediately after). Not a code failure, an external quota state, and the equivalent logic path is covered deterministically by MockedNegativeCaseTests above.

## Full run output

```
test_exactly_100_percent_is_on_track_not_over (tests.test_pulse_core.BudgetBoundaryTests.test_exactly_100_percent_is_on_track_not_over) ... ok
test_exactly_at_near_limit_threshold (tests.test_pulse_core.BudgetBoundaryTests.test_exactly_at_near_limit_threshold) ... ok
test_just_under_near_limit_threshold (tests.test_pulse_core.BudgetBoundaryTests.test_just_under_near_limit_threshold) ... ok
test_one_dollar_over_is_over (tests.test_pulse_core.BudgetBoundaryTests.test_one_dollar_over_is_over) ... ok
test_planned_zero_does_not_crash (tests.test_pulse_core.BudgetBoundaryTests.test_planned_zero_does_not_crash) ... ok
test_ci_failure_overrides_active_delivery (tests.test_pulse_core.CodeHealthPriorityTests.test_ci_failure_overrides_active_delivery) ... ok
test_ci_failure_overrides_stale_too (tests.test_pulse_core.CodeHealthPriorityTests.test_ci_failure_overrides_stale_too) ... ok
test_no_ci_configured_on_active_project (tests.test_pulse_core.CodeHealthPriorityTests.test_no_ci_configured_on_active_project) ... ok
test_stale_overrides_no_ci_configured (tests.test_pulse_core.CodeHealthPriorityTests.test_stale_overrides_no_ci_configured) ... ok
test_missing_both_sources_entirely (tests.test_pulse_core.MissingDataTests.test_missing_both_sources_entirely) ... ok
test_missing_budget_data (tests.test_pulse_core.MissingDataTests.test_missing_budget_data) ... ok
test_missing_github_data (tests.test_pulse_core.MissingDataTests.test_missing_github_data) ... ok
test_risk_tier_unknown_when_no_data_either_side (tests.test_pulse_core.MissingDataTests.test_risk_tier_unknown_when_no_data_either_side) ... ok
test_all_clear_portfolio_says_no_action (tests.test_pulse_core.PortfolioInterpretationTests.test_all_clear_portfolio_says_no_action) ... ok
test_empty_portfolio_does_not_crash (tests.test_pulse_core.PortfolioInterpretationTests.test_empty_portfolio_does_not_crash) ... ok
test_budget_over_alone_gives_correct_reason (tests.test_pulse_core.RiskTierAndInterpretationTests.test_budget_over_alone_gives_correct_reason) ... ok
test_ci_failure_and_budget_over_simultaneously (tests.test_pulse_core.RiskTierAndInterpretationTests.test_ci_failure_and_budget_over_simultaneously) ... ok
test_negative_ticket_net_reads_as_shrinking (tests.test_pulse_core.RiskTierAndInterpretationTests.test_negative_ticket_net_reads_as_shrinking) ... ok
test_ticket_net_exactly_at_watch_threshold (tests.test_pulse_core.RiskTierAndInterpretationTests.test_ticket_net_exactly_at_watch_threshold) ... ok
test_ticket_net_just_under_watch_threshold (tests.test_pulse_core.RiskTierAndInterpretationTests.test_ticket_net_just_under_watch_threshold) ... ok
test_one_repo_raising_does_not_abort_the_batch (tests.test_github_pull.BatchResilienceTests.test_one_repo_raising_does_not_abort_the_batch) ... ok
test_empty_string_returns_none (tests.test_github_pull.DaysSinceTests.test_empty_string_returns_none) ... ok
test_malformed_timestamp_raises_rather_than_silently_wrong (tests.test_github_pull.DaysSinceTests.test_malformed_timestamp_raises_rather_than_silently_wrong) ... ok
test_none_input_returns_none (tests.test_github_pull.DaysSinceTests.test_none_input_returns_none) ... ok
test_valid_recent_timestamp (tests.test_github_pull.DaysSinceTests.test_valid_recent_timestamp) ... ok
test_commit_entry_not_a_dict_handled_gracefully (tests.test_github_pull.InputValidationTests.test_commit_entry_not_a_dict_handled_gracefully) ... ok
test_commit_missing_nested_fields_handled_gracefully (tests.test_github_pull.InputValidationTests.test_commit_missing_nested_fields_handled_gracefully) ... ok
test_empty_commit_list_returns_none_none (tests.test_github_pull.InputValidationTests.test_empty_commit_list_returns_none_none) ... ok
test_well_formed_commit_extracts_correctly (tests.test_github_pull.InputValidationTests.test_well_formed_commit_extracts_correctly) ... ok
test_live_dormant_repo_is_stale (tests.test_github_pull.LiveIntegrationTests.test_live_dormant_repo_is_stale) ... skipped 'dormant-repo staleness check: GitHub API rate limit was exhausted during this attempt (0 remaining, confirmed immediately after). Not a code failure, an external quota state, and the equivalent logic path is covered deterministically by MockedNegativeCaseTests above.'
test_live_nonexistent_repo_returns_none (tests.test_github_pull.LiveIntegrationTests.test_live_nonexistent_repo_returns_none) ... ok
test_live_repo_with_no_ci_configured (tests.test_github_pull.LiveIntegrationTests.test_live_repo_with_no_ci_configured) ... skipped 'no-CI-configured check: GitHub API rate limit was exhausted during this attempt (0 remaining, confirmed immediately after). Not a code failure, an external quota state, and the equivalent logic path is covered deterministically by MockedNegativeCaseTests above.'
test_404_on_repo_lookup_returns_none_not_a_crash (tests.test_github_pull.MockedNegativeCaseTests.test_404_on_repo_lookup_returns_none_not_a_crash) ... ok
test_ci_status_detects_failure_in_check_runs (tests.test_github_pull.MockedNegativeCaseTests.test_ci_status_detects_failure_in_check_runs) ... ok
test_ci_status_falls_back_to_legacy_when_check_runs_empty (tests.test_github_pull.MockedNegativeCaseTests.test_ci_status_falls_back_to_legacy_when_check_runs_empty) ... ok
test_ci_status_no_check_runs_and_no_legacy_status (tests.test_github_pull.MockedNegativeCaseTests.test_ci_status_no_check_runs_and_no_legacy_status) ... ok
test_ci_status_no_sha_returns_no_ci_configured_without_any_call (tests.test_github_pull.MockedNegativeCaseTests.test_ci_status_no_sha_returns_no_ci_configured_without_any_call) ... ok
test_partial_failure_on_commit_lookup_does_not_report_false_active (tests.test_github_pull.MockedNegativeCaseTests.test_partial_failure_on_commit_lookup_does_not_report_false_active) ... ok
test_pull_repo_status_none_when_repo_itself_404s (tests.test_github_pull.MockedNegativeCaseTests.test_pull_repo_status_none_when_repo_itself_404s) ... ok
test_rate_limit_response_returns_none_not_a_crash (tests.test_github_pull.MockedNegativeCaseTests.test_rate_limit_response_returns_none_not_a_crash) ... ok
test_403_rate_limit_never_retries (tests.test_github_pull.RetryLogicTests.test_403_rate_limit_never_retries) ... ok
test_404_never_retries (tests.test_github_pull.RetryLogicTests.test_404_never_retries) ... ok
test_5xx_exhausts_retries_and_returns_none (tests.test_github_pull.RetryLogicTests.test_5xx_exhausts_retries_and_returns_none) ... ok
test_5xx_retries_then_succeeds (tests.test_github_pull.RetryLogicTests.test_5xx_retries_then_succeeds) ... ok
test_connection_error_retries_then_succeeds (tests.test_github_pull.RetryLogicTests.test_connection_error_retries_then_succeeds) ... ok
test_hard_cap_stops_a_model_that_never_stops_calling_tools (tests.test_agent_eval.AgentEvalTests.test_hard_cap_stops_a_model_that_never_stops_calling_tools)
A model that always wants another tool call must not loop ... ok
test_multi_round_tool_orchestration (tests.test_agent_eval.AgentEvalTests.test_multi_round_tool_orchestration)
Scripted model calls list_projects, then drills into one ... ok
test_single_tool_call_then_final_answer (tests.test_agent_eval.AgentEvalTests.test_single_tool_call_then_final_answer)
Scripted model asks for list_projects, gets the REAL result ... ok
test_unknown_repo_surfaces_structured_error_not_a_crash (tests.test_agent_eval.AgentEvalTests.test_unknown_repo_surfaces_structured_error_not_a_crash)
Re-runs the exact scenario MCP_VERIFICATION_LOG.md's bug fix ... ok
test_degraded_run_is_a_warning_not_critical (tests.test_pulse_alert.AlertConditionTests.test_degraded_run_is_a_warning_not_critical) ... ok
test_healthy_run_above_threshold_is_not_degraded (tests.test_pulse_alert.AlertConditionTests.test_healthy_run_above_threshold_is_not_degraded) ... ok
test_healthy_run_triggers_nothing (tests.test_pulse_alert.AlertConditionTests.test_healthy_run_triggers_nothing) ... ok
test_malformed_log_line_is_skipped_not_fatal (tests.test_pulse_alert.AlertConditionTests.test_malformed_log_line_is_skipped_not_fatal) ... ok
test_no_log_file_is_healthy (tests.test_pulse_alert.AlertConditionTests.test_no_log_file_is_healthy) ... ok
test_run_never_finished_is_critical (tests.test_pulse_alert.AlertConditionTests.test_run_never_finished_is_critical) ... ok
test_single_bad_run_after_good_ones_is_not_called_repeated (tests.test_pulse_alert.AlertConditionTests.test_single_bad_run_after_good_ones_is_not_called_repeated) ... ok
test_total_failure_is_critical_and_names_repos_and_reasons (tests.test_pulse_alert.AlertConditionTests.test_total_failure_is_critical_and_names_repos_and_reasons) ... ok
test_two_consecutive_total_failures_trigger_the_repeated_alert (tests.test_pulse_alert.AlertConditionTests.test_two_consecutive_total_failures_trigger_the_repeated_alert) ... ok
test_network_failure_returns_false_not_raises (tests.test_pulse_alert.SendAlertTests.test_network_failure_returns_false_not_raises) ... ok
test_no_webhook_configured_prints_and_returns_false (tests.test_pulse_alert.SendAlertTests.test_no_webhook_configured_prints_and_returns_false) ... ok
test_successful_webhook_post_returns_true (tests.test_pulse_alert.SendAlertTests.test_successful_webhook_post_returns_true) ... ok
test_webhook_error_response_returns_false_not_raises (tests.test_pulse_alert.SendAlertTests.test_webhook_error_response_returns_false_not_raises) ... ok
test_extract_numbers_basic (tests.test_grounding_eval.ExtractionTests.test_extract_numbers_basic) ... ok
test_extract_numbers_empty_on_no_digits (tests.test_grounding_eval.ExtractionTests.test_extract_numbers_empty_on_no_digits) ... ok
test_extract_numbers_handles_decimals (tests.test_grounding_eval.ExtractionTests.test_extract_numbers_handles_decimals) ... ok
test_extract_status_claims_case_insensitive (tests.test_grounding_eval.ExtractionTests.test_extract_status_claims_case_insensitive) ... ok
test_extract_status_claims_only_matches_known_vocabulary (tests.test_grounding_eval.ExtractionTests.test_extract_status_claims_only_matches_known_vocabulary) ... ok
test_answer_with_no_numbers_or_statuses_is_vacuously_grounded (tests.test_grounding_eval.GroundingCheckTests.test_answer_with_no_numbers_or_statuses_is_vacuously_grounded) ... ok
test_empty_tool_log_with_numeric_claim_fails (tests.test_grounding_eval.GroundingCheckTests.test_empty_tool_log_with_numeric_claim_fails) ... ok
test_fabricated_number_fails (tests.test_grounding_eval.GroundingCheckTests.test_fabricated_number_fails) ... ok
test_fabricated_status_word_fails (tests.test_grounding_eval.GroundingCheckTests.test_fabricated_status_word_fails) ... ok
test_fully_grounded_answer_passes (tests.test_grounding_eval.GroundingCheckTests.test_fully_grounded_answer_passes) ... ok
test_data_question_with_zero_tool_calls_fails_even_with_grounded_text (tests.test_grounding_eval.RunOneEvalGroundingLogicTests.test_data_question_with_zero_tool_calls_fails_even_with_grounded_text) ... ok
test_200_is_changed_and_updates_cache (tests.test_pulse_scheduler.CheckRepoChangedTests.test_200_is_changed_and_updates_cache) ... ok
test_304_is_not_changed (tests.test_pulse_scheduler.CheckRepoChangedTests.test_304_is_not_changed) ... ok
test_failed_request_is_unknown_not_changed (tests.test_pulse_scheduler.CheckRepoChangedTests.test_failed_request_is_unknown_not_changed) ... ok
test_prior_etag_is_passed_through_to_get_fn (tests.test_pulse_scheduler.CheckRepoChangedTests.test_prior_etag_is_passed_through_to_get_fn) ... ok
test_unexpected_status_is_unknown_not_changed (tests.test_pulse_scheduler.CheckRepoChangedTests.test_unexpected_status_is_unknown_not_changed) ... ok
test_cap_counts_only_the_trailing_window_not_all_history (tests.test_pulse_scheduler.DecideTests.test_cap_counts_only_the_trailing_window_not_all_history) ... ok
test_cap_reached_blocks_baseline_and_priority_both (tests.test_pulse_scheduler.DecideTests.test_cap_reached_blocks_baseline_and_priority_both) ... ok
test_failed_pulls_still_count_toward_the_cap (tests.test_pulse_scheduler.DecideTests.test_failed_pulls_still_count_toward_the_cap) ... ok
test_last_pull_exactly_at_boundary_is_baseline_due (tests.test_pulse_scheduler.DecideTests.test_last_pull_exactly_at_boundary_is_baseline_due) ... ok
test_last_pull_over_24h_ago_is_baseline_due (tests.test_pulse_scheduler.DecideTests.test_last_pull_over_24h_ago_is_baseline_due) ... ok
test_no_history_is_baseline_due (tests.test_pulse_scheduler.DecideTests.test_no_history_is_baseline_due) ... ok
test_recent_pull_no_change_detected_is_not_due (tests.test_pulse_scheduler.DecideTests.test_recent_pull_no_change_detected_is_not_due) ... ok
test_recent_pull_no_repos_checked_is_not_due (tests.test_pulse_scheduler.DecideTests.test_recent_pull_no_repos_checked_is_not_due) ... ok
test_recent_pull_with_change_is_priority_trigger (tests.test_pulse_scheduler.DecideTests.test_recent_pull_with_change_is_priority_trigger) ... ok
test_unknown_change_result_never_triggers_a_pull (tests.test_pulse_scheduler.DecideTests.test_unknown_change_result_never_triggers_a_pull) ... ok
test_ignores_non_run_started_events (tests.test_pulse_scheduler.LoadRunStartedTimesTests.test_ignores_non_run_started_events) ... ok
test_missing_log_file_is_empty_not_fatal (tests.test_pulse_scheduler.LoadRunStartedTimesTests.test_missing_log_file_is_empty_not_fatal) ... ok
test_results_are_sorted (tests.test_pulse_scheduler.LoadRunStartedTimesTests.test_results_are_sorted) ... ok
test_skips_malformed_lines (tests.test_pulse_scheduler.LoadRunStartedTimesTests.test_skips_malformed_lines) ... ok

----------------------------------------------------------------------
Ran 92 tests in 3.946s

OK (skipped=2)
```