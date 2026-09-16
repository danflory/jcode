# SPR-0007: Configured OpenAI-compatible profiles not counted as available auth

## Status
Closed (fixed by commit `677462389`, cherry-picked from `7a6ea59ef`)

## Severity
Major

## Affected component
`crates/jcode-base/src/auth/mod.rs` (`probe_openrouter_status` /
`has_any_available`)

## Environment
- Commits: `7a6ea59ef` (original, authored by Dan Flory on the `WithLocalMods`
  branch), cherry-picked onto `dev` as `677462389`
- Author: Dan Flory
- Date (when): 2026-09-15

## What
OpenAI-compatible catalog profiles (deepinfra, groq, chutes, ...) share the
OpenRouter slot via runtime env overrides, but `probe_openrouter_status`'s
strict `provider_features_enabled` check only accepted keys whose API base
contains `openrouter.ai`. A fully working deepinfra install therefore reported
**no credentials anywhere**.

## Why
Because `has_any_available` came back false, the TUI first-run onboarding
(`check_fast` probe -> `has_any_available` -> `begin_onboarding_flow_at_login`)
showed the login splash on **every launch** for users whose `launch_count` was
still low, even though their API key was fully configured and working.

## When
Reported/fixed 2026-09-15.

## What changed
- After the existing OpenRouter early-return, added a fallback that scans the
  OpenAI-compatible catalog profiles for any configured API key
  (`openai_compatible_profiles` +
  `openai_compatible_profile_is_configured`).
- When a profile has a configured key, marks the OpenRouterLike slot
  `Available`.
- Existing OpenRouter behavior is untouched via the early return.

## Verification
A configured DeepInfra (or other OpenAI-compatible) API key is now counted as
available auth, so first-run onboarding no longer shows the login splash on
every launch for an already-working install.
