# Task 1 progress

Round 1 over-claimed; corrected after independent review on 2026-10-01.

Branch: `task1-fixes`, based on `4169522`. Changes remain uncommitted because a prior direct user instruction said not to commit or push. The `.git` directory is read-only in this environment, so Git index operations are unavailable. No `.env` file or `meta_cred.md` was opened.

> **Independent verification (2026-10-01, Claude Code):** on the developer machine `py -3.12` (Python 3.12.0) runs the full suite: **128 passed**. The "Python 3.12 unavailable" and "`.git` read-only" notes below describe the Codex sandbox only. The F3 mutation (re-adding a `state["customer_id"]` fallback) makes `test_n6_real_path_identity_enforcement` fail as intended. Renames were staged outside the sandbox.

## Phase status

| Phase | Status | Notes |
|---|---|---|
| Phase 0: baseline and ledger | done | Round 1 baseline in prior ledger was 57 passed. Round 2 baseline in the isolated Python 3.14 venv was 62 passed before source changes. |
| Phases 1–6: fixes and QA | done | Fixes and repro tests are present. Round 2 independent verification completed: 23 repros passed, followed by four R8 lifecycle tests. Round 3 full local suite passes under Python 3.14. |
| Phase 7: structure cleanup | complete in worktree; staging pending | Test files and data were physically moved; collection is 128 tests. Git staging is still needed to record renames, but `.git` is read-only here. The Python 3.12 launcher check fails in this environment; local verification uses Python 3.14. |

## Round 2 ledger

| ID | Status | Repro/test | Fail-before evidence | Current evidence / limit |
|---|---|---|---|---|
| R1 | fixed | `test_approved_refund_cannot_be_requested_again`, `test_rejected_refund_is_returned_without_creating_another_action`, `test_approved_cancellation_is_not_created_again`, `test_approved_replacement_is_not_created_again`, `test_rejected_cancellation_returns_rejection_without_new_action` | Action group repro suite: 10 failures before fixes. | Full suite passed. Shared active-status set covers refund, replacement, and cancellation. |
| R2 | fixed | `test_delivered_refund_and_replacement_require_human_approval` | Action group repro suite: 10 failures before fixes. | Delivered claims require human approval regardless of customer wording. |
| R3 | fixed | `test_invalid_refund_amount_never_auto_creates` | Action group repro suite: 10 failures before fixes. | Rejects bool, non-finite, non-positive, missing, and nonnumeric amounts from auto-creation. |
| R4 | fixed | `test_r4_action_then_service_error_is_never_retried`, `test_f2_clean_stream_after_action_is_not_retried` | Core repro suite initially had 5 failures. | Both failure-after-action and clean-end-after-action avoid replaying the pipeline. |
| R5 | fixed with R8 | `test_support_case_records_intent_without_writing_or_minting_a_ticket_id` | No separate retained fail-before output. | Tool records escalation intent; backend owns ticket creation. |
| R6 | fixed | `test_r6_concurrent_request_id_is_claimed_once`, `test_r6_failed_retry_reuses_user_message_and_is_per_user` | Core repro suite initially had 5 failures. | Unique `(user_id, request_id)` claim, concurrency, failed retry reuse, and per-user isolation are covered. |
| R7 | fixed | `test_r7_chat_message_reuses_request_id_on_retry` | Auth/frontend repro tests: 11 failures before fixes. | Browser behavior was not manually exercised; source test checks generation, send, and retry reuse. |
| R8 | fixed | `test_r8_escalation_reply_uses_active_ticket_id_and_reopens_resolved`, `test_r8_concurrent_ticket_upsert_returns_unique_winner`, `test_r8_active_ticket_key_has_unique_sparse_index`, `test_r8_unique_ticket_key_only_applies_to_conversation_tickets`, `test_h1_duplicate_support_tickets` | Core repro suite initially had 5 failures. | Ticket route owns ID; a sparse unique active-ticket key prevents concurrent duplicate upserts, and duplicate-key races return the winning ticket. Reviewer confirmed the four R8 lifecycle tests pass. |
| R9 | fixed | `test_r9_ticket_update_failure_is_reported_and_request_stays_retryable` | Core repro suite initially had 5 failures. | Failed ticket update returns an error and leaves request retryable. |
| R10 | fixed | `test_rag_outage_is_distinct_from_empty_collection`, `test_health_reports_rag_outage` | RAG repro suite: 4 failures before fixes. | Healthy-empty and unavailable retrieval differ; health exposes outage. |
| R11 | fixed | `test_replace_indexes_new_version_then_supersedes_old`, `test_index_status_failure_rolls_back_new_chunks`, `test_partial_chroma_write_is_rolled_back`, `test_delete_chroma_failure_keeps_mongo_document`, `test_chunk_delete_propagates_chroma_failure` | RAG repro suite: 4 failures before fixes. | Replacement and rollback paths are covered by the RAG round 2 tests. |
| R12 | fixed | `test_r12_no_tool_accepts_customer_id_override` | Core repro suite initially had 5 failures. | Removes public customer ID overrides; declarations are checked through the registered tool signatures. |
| R13 | fixed | `test_n6_real_path_identity_enforcement` | Round 1 assertion was vacuous. | Real C102 session is seeded with hostile C101 state; a direct legacy-only check proves the fallback regression fails. Scratch-copy failing output is recorded below. |
| R14 | fixed | `test_r14_jwt_placeholder_secret_rejected`, `test_r14_app_startup_rejects_jwt_placeholders`, `test_r14_all_env_examples_leave_jwt_secret_empty` | Auth repro tests: 11 failures before fixes. | Placeholder JWT secrets rejected; all examples leave the value empty. |
| R15 | fixed | `test_r15_registration_returns_same_generic_response_for_new_and_existing_email` | Auth repro tests: 11 failures before fixes. | Both cases return 202 and the same body. Trade-off: without email verification, a mistyped address gets no clear error. |
| R16 | fixed | `test_r16_login_rate_limit_is_shared_across_emails_and_has_retry_after`, `test_r16_expired_login_rate_limit_keys_are_pruned` | Auth repro tests: 11 failures before fixes. | Shared IP limit and expired-key pruning covered. |
| R17 | fixed | `test_r17_empty_final_response_is_an_error` | Core repro suite initially had 5 failures. | Empty final text is an explicit `empty_response` failure. |
| R18 | fixed | `test_r18_session_hydration_error_fails_workflow` | Core repro suite initially had 5 failures. | History hydration failure is returned as `history_unavailable`. |
| R19 | fixed | `test_r19_hydration_skips_failed_turns`, `test_r6_failed_retry_reuses_user_message_and_is_per_user` | Core repro suite initially had 5 failures. | Failed turns are skipped and retry clears the user message failure marker. |
| R20 | fixed | `test_r20_corrupt_agent_data_raises_without_changing_file`, `test_m6_corrupt_json_fails_closed` | Core repro suite initially had 5 failures. | Corrupt JSON raises and remains unchanged. |
| R21 | fixed with deviation | `test_r21_file_store_and_action_paths_are_test_local`; root `conftest.py` session data-isolation check | Existing tests could touch tracked data; no retained single fail-before trace. | Tests use temp data paths and compare data-path status/diffs before and after. This is adapted to the intentionally dirty no-commit worktree; it does not use the prompt's literal “directory status must be empty” check. |
| R22 | fixed | `test_r22_same_identity_does_not_append_empty_session_delta`; `test_m7_production_dependencies`; `test_n8_single_process_store_limit_documented` | Core repro suite initially had 5 failures. | State deltas, pinned `pypdf`, and the documented single-process file-store limit are covered. |

## Phase 5 self-check and missing round 1 tests

| Item | Status | Test / evidence |
|---|---|---|
| N1 | fixed | `test_n1_existing_customer_email_is_not_linked_on_registration` |
| N4 | fixed | `test_n4_two_registrations_get_distinct_customer_ids` |
| C7 | fixed | `test_r14_app_startup_rejects_jwt_placeholders`, `test_c7_jwt_secret_security` |
| M3 | fixed | `test_r16_login_rate_limit_is_shared_across_emails_and_has_retry_after` |
| N7 | fixed | `test_n7_environment_value_beats_dotenv_file` |
| N9 | fixed | `test_n9_pytest_config_has_no_blanket_userwarning_ignore` |
| N5 | fixed | `test_n5_admin_ticket_dropdown_values_match_ticket_status_enum`; dropdown options parsed against backend enum |
| N10 | fixed | `test_n10_no_obsolete_mobile_menu_button_reference` |
| L1 | fixed | `test_l1_documentation_consistency`; root README replaced, implementation progress file removed, environment examples aligned |
| L2 | fixed | `test_l2_dead_code_and_case_id_uniqueness`; dead agents and servers removed, policy tool retained |
| PR | accepted | `test_pr_model_defaults_are_defined_once_and_db_accessors_are_typed` |
| L4 | fixed | `test_l4_feedback_cannot_claim_to_remove_persisted_rating`; unselect sends clear request |
| L5 | fixed | `test_l5_api_origin_fallbacks_removed_and_shared_config_loaded` |
| M8 | fixed; Python-version limit | `.github/workflows/ci.yml`; full local suite | — | Full local suite passed in the isolated Python 3.14.6 venv while `backend/.env` was temporarily renamed and restored. Python 3.12 clean-venv run remains unavailable. |
| Test isolation | fixed with R21 deviation | Root `conftest.py` isolates runtime paths; redundant `backend/conftest.py` removed. |
| Ponytail | fixed | `**kwargs` removed from business tool signatures; duplicate copy-button construction consolidated in F6; escalation print calls removed. |

## Verification

- Baseline before round 2 source changes: 62 passed in the isolated Python 3.14.6 venv.
- Round 2 collection was 123 tests. Round 3 added five tests (two F1, one F2, one F6, one single-process documentation check); current collection is 128.
- Round 3 full run: `rtk .venv-task1\Scripts\python.exe -m pytest -q` — 128 passed; one Google ADK experimental-feature warning.
- Final clean-environment simulation: same command passed with `backend/.env` temporarily renamed; it was restored and the temporary name removed afterward. The runtime was Python 3.14.6, not Python 3.12.
- `rtk py -3.12 --version` reports “No suitable Python runtime found”; `rtk py -0p` lists only Python 3.14. The requested Python 3.12 run remains unverified.
- No commit hashes: skipped because of the prior direct instruction not to commit. No push, PR, or merge performed.
- Package rename skipped: keeping `final_customer_support` avoids a broad import/script/docs migration unrelated to the fixes.
- An independent reviewer ran the requested action, idempotency, ticket, RAG, and tool-declaration repros: 23 passed. After the R8 concurrency/lifecycle changes, the reviewer reran all four R8 tests and confirmed the active-ticket uniqueness guard and lifecycle handling.

## Decisions and remaining questions

- The no-commit instruction takes precedence over the round 2 prompt's commit directions. Work is left in the working tree. Six packet-level patch bundles are in `%TEMP%\task1-round2-review-patches\`; they group changes by packet and include shared-file diffs where needed for review.
- F8 rename staging is pending because `.git` is read-only in this environment. Python 3.12 is unavailable here; the complete suite passed under Python 3.14.

## Round 3 final loose ends

| Item | Status | Test / evidence |
|---|---|---|
| F1 | fixed | `test_f1_assistant_save_failure_releases_request_for_retry`; `test_f1_stale_in_progress_request_can_be_retried` |
| F2 | fixed | `test_f2_clean_stream_after_action_is_not_retried` |
| F3 | fixed | `test_n6_real_path_identity_enforcement`; scratch-copy fallback experiment below |
| F4 | fixed | `test_l1_documentation_consistency` verifies documented method/path pairs against included `app.routes`; README route and environment tables corrected |
| F5 | fixed | `test_l2_dead_code_and_case_id_uniqueness`; `test_m7_production_dependencies`; stale references removed; design decisions recorded in README |
| F6 | fixed | `test_f6_copy_button_builder_is_shared_by_both_message_types`; `node --check frontend/customer/app.js` passed |
| F7 | fixed | `test_n8_single_process_store_limit_documented`; progress claims corrected; PR accessor type recorded as `Any` (pymongo/mongomock union), accepted |
| F8 | pending user | `.git` index is read-only here; no staging claimed |

F3 scratch-copy experiment: copied the repository to a temporary directory, reintroduced `state.get("customer_id")` as a fallback for authenticated identity, and ran `backend/tests/integration/test_n6_real_path_integration.py`. The regression was caught:

```text
FAILED backend/tests/integration/test_n6_real_path_integration.py::test_n6_real_path_identity_enforcement
E       AssertionError: {'order_id': 'ORD123', 'customer_id': 'C101', ...}
E       assert 'Access denied' in "{'order_id': 'ORD123', 'customer_id': 'C101', ...}"
```

This direct legacy-only check ensures the fallback test fails; the real C102 session also carries hostile `customer_id = C101` state. The complete current suite collected 128 tests and passed 128 under the Python 3.14.6 virtual environment. Python 3.12 could not be located by the launcher in this environment.
