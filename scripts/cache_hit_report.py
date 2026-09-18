#!/usr/bin/env python3
"""Report prompt-cache hit rates from jcode session history, split by role and by
whether the session predates the SPR-0010 session-context fix.

Why this exists
---------------
SPR-0010 changed the order of fields in the leading provider-visible
session-context block so that stable fields come first and volatile ones
(the timestamp) come last. Prefix caching matches on a byte-identical prefix, so
the old ordering capped the shared prefix between any two sessions at ~60 chars.

The cost effect of that fix can only be measured as a *sustained* cache hit rate
over real traffic, which takes time to accumulate. This script makes that
measurement a single command:

    python3 scripts/cache_hit_report.py

Classification caveat (learned the hard way)
--------------------------------------------
Do NOT classify sessions as pre/post-fix by searching the file for the build
hash. The hash appears in tool output and session metadata, so that approach
produces false positives and will report pre-fix sessions as post-fix. Classify
by the **context block ordering itself**: post-fix iff `Date:` appears after
`OS:`.

Token fields live under `messages[].token_usage` (NOT `usage`):
    cache_read_input_tokens, input_tokens, output_tokens
`input_tokens` is the TOTAL input, with `cache_read_input_tokens` a subset, so
uncached = input_tokens - cache_read_input_tokens. Treating the two as disjoint
double-counts input and roughly halves the apparent hit rate.

Root vs child: a session with no `parent_id` is a coordinator/root session; one
with a `parent_id` is a spawned worker.
"""

import glob
import json
import os
import sys
from collections import defaultdict

SESSIONS_GLOB = os.path.expanduser("~/.jcode/sessions/*.json")


def context_block(session):
    """Return the leading session-context text, or None if absent."""
    for message in (session.get("messages") or [])[:2]:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and isinstance(block.get("text"), str)
                    and block["text"].startswith("<system-reminder>")
                ):
                    return block["text"]
    return None


def is_post_fix(context_text):
    """True if the context block uses the SPR-0010 ordering (stable fields first).

    Returns None when the block is unparseable or absent.
    """
    if not context_text:
        return None
    lines = context_text.splitlines()
    try:
        os_line = next(i for i, l in enumerate(lines) if l.startswith("OS: "))
        date_line = next(i for i, l in enumerate(lines) if l.startswith("Date: "))
    except StopIteration:
        return None
    return date_line > os_line


def collect():
    stats = defaultdict(lambda: {"turns": 0, "cache_read": 0, "uncached": 0, "output": 0})
    skipped = 0
    for path in glob.glob(SESSIONS_GLOB):
        if not path.endswith(".json"):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                session = json.load(handle)
        except (json.JSONDecodeError, OSError):
            skipped += 1
            continue
        if not isinstance(session, dict):
            skipped += 1
            continue

        post_fix = is_post_fix(context_block(session))
        if post_fix is None:
            skipped += 1
            continue

        era = "POST-FIX" if post_fix else "pre-fix"
        role = "child" if session.get("parent_id") else "root"
        model = session.get("model") or "unknown"

        for message in session.get("messages") or []:
            usage = message.get("token_usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            cache_read = usage.get("cache_read_input_tokens") or 0
            total_input = usage.get("input_tokens") or 0
            output = usage.get("output_tokens") or 0
            if not (cache_read or total_input or output):
                continue
            entry = stats[(era, role, model)]
            entry["turns"] += 1
            entry["cache_read"] += cache_read
            entry["uncached"] += max(total_input - cache_read, 0)
            entry["output"] += output
    return stats, skipped


def main():
    stats, skipped = collect()
    if not stats:
        print("No usable sessions found under", SESSIONS_GLOB, file=sys.stderr)
        return 1

    print(f"{'era':<9} {'role':<6} {'model':<36} {'turns':>6} {'cache_read':>14} {'hit%':>7}")
    print("-" * 84)
    for (era, role, model), entry in sorted(stats.items()):
        denom = entry["cache_read"] + entry["uncached"]
        hit = (entry["cache_read"] / denom * 100) if denom else 0.0
        print(
            f"{era:<9} {role:<6} {model[-36:]:<36} {entry['turns']:>6} "
            f"{entry['cache_read']:>14,} {hit:>6.1f}%"
        )

    # Aggregate per era+role, which is the figure to compare across the fix.
    print()
    print(f"{'era':<9} {'role':<6} {'turns':>6} {'cache_read':>14} {'uncached':>14} {'hit%':>7}")
    print("-" * 62)
    rolled = defaultdict(lambda: {"turns": 0, "cache_read": 0, "uncached": 0})
    for (era, role, _model), entry in stats.items():
        key = (era, role)
        for field in ("turns", "cache_read", "uncached"):
            rolled[key][field] += entry[field]
    for (era, role), entry in sorted(rolled.items()):
        denom = entry["cache_read"] + entry["uncached"]
        hit = (entry["cache_read"] / denom * 100) if denom else 0.0
        print(
            f"{era:<9} {role:<6} {entry['turns']:>6} {entry['cache_read']:>14,} "
            f"{entry['uncached']:>14,} {hit:>6.1f}%"
        )

    post_child = rolled.get(("POST-FIX", "child"))
    if not post_child or post_child["turns"] < 200:
        print()
        print(
            "NOTE: post-fix child (worker) sample is still small"
            f" ({post_child['turns'] if post_child else 0} turns). Treat any"
            " post-fix worker figure as provisional until this is a few hundred"
            " turns, so a handful of short sessions cannot masquerade as a trend."
        )

    print()
    print(f"skipped (unreadable / no context block): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
