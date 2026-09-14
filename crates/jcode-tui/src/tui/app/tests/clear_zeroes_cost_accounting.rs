// `/clear` must zero the session cost/token accounting.
//
// Both `/clear` implementations funnel their full-discard usage reset through
// `App::clear_live_usage_state`, but that hook originally zeroed only the live
// streaming counters. The accumulated `cost.total_cost` and
// `token_accounting.total_*` (plus history-restored totals) survived the clear,
// so the info widget kept showing the discarded session's spend. Cover the
// shared hook and the `reset_current_session` caller that users hit on the
// local/test-harness path.

use crate::tui::app::tests::create_test_app;

fn seed_accounting(app: &mut crate::tui::app::App) {
    app.cost.total_cost = 1.39;
    app.token_accounting.total_input_tokens = 23_000_000;
    app.token_accounting.total_output_tokens = 211_000;
    app.token_accounting.total_cache_reported_input_tokens = 20_000_000;
    app.token_accounting.total_cache_read_tokens = 19_000_000;
    app.token_accounting.total_cache_creation_tokens = 0;
    app.token_accounting.total_cache_optimal_input_tokens = 19_500_000;
    app.token_accounting.last_cache_read_tokens = Some(128_000);
    app.token_accounting.cache_next_optimal_input_tokens = Some(128_000);
    app.remote_total_tokens = Some((23_000_000, 211_000));
    app.remote_token_usage_totals = Some(crate::protocol::TokenUsageTotals {
        messages_with_token_usage: 71,
        input_tokens: 5_164_241,
        output_tokens: 34_113,
        cache_reported_input_tokens: 3_692_032,
        cache_read_input_tokens: 3_692_032,
        cache_creation_input_tokens: 0,
    });
}

fn assert_accounting_zeroed(app: &crate::tui::app::App, ctx: &str) {
    assert_eq!(app.cost.total_cost, 0.0, "{ctx}: cost must be zeroed");
    assert_eq!(
        app.token_accounting.total_input_tokens, 0,
        "{ctx}: input tokens must be zeroed"
    );
    assert_eq!(
        app.token_accounting.total_output_tokens, 0,
        "{ctx}: output tokens must be zeroed"
    );
    assert_eq!(
        app.token_accounting.total_cache_reported_input_tokens, 0,
        "{ctx}: cache-reported input must be zeroed"
    );
    assert_eq!(
        app.token_accounting.total_cache_read_tokens, 0,
        "{ctx}: cache-read tokens must be zeroed"
    );
    assert_eq!(
        app.token_accounting.total_cache_optimal_input_tokens, 0,
        "{ctx}: cache-optimal input must be zeroed"
    );
    assert!(
        app.remote_total_tokens.is_none(),
        "{ctx}: history-restored totals must be dropped"
    );
    assert!(
        app.remote_token_usage_totals.is_none(),
        "{ctx}: history-restored usage totals must be dropped"
    );
    assert!(
        app.token_accounting.last_cache_read_tokens.is_none(),
        "{ctx}: last cache-read telemetry must be dropped"
    );
    assert!(
        app.token_accounting.cache_next_optimal_input_tokens.is_none(),
        "{ctx}: pending cache-optimal estimate must be dropped"
    );
}

#[test]
fn clear_live_usage_state_zeroes_cost_and_token_accounting() {
    let mut app = create_test_app();
    seed_accounting(&mut app);

    app.clear_live_usage_state();

    assert_accounting_zeroed(&app, "clear_live_usage_state");
}

#[test]
fn reset_current_session_zeroes_cost_and_token_accounting() {
    let mut app = create_test_app();
    seed_accounting(&mut app);

    crate::tui::app::commands_review::reset_current_session(&mut app);

    assert_accounting_zeroed(&app, "reset_current_session");
}
