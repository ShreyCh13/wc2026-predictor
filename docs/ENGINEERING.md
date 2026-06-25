# Engineering Notes

The quality posture of the codebase, for anyone reading or extending it.

## Correctness

- Standings use the 2026 FIFA tiebreaker order: points → head-to-head (points, goal
  difference, then goals among the level teams) → overall goal difference → overall goals.
  Head-to-head ranking *before* overall goal difference is new for 2026, and the head-to-head
  step is a proper mini-league among the tied teams, re-applied to any subset that stays level.
- Third-place qualification and Round-of-32 placement follow FIFA's official 495-combination
  Annex C table, parsed from primary sources; a test asserts that every row respects the
  eligibility constraints and uses each qualifying group exactly once.
- Bracket linkages (which match feeds which) match the official schedule, checked line by line.
- Scoring: 5 points for an exact score, 2 for the right winner, plus round-weighted points for
  correctly predicting who advances through the knockouts.
- The engine and the FIFA table are covered by headless tests — `node tests/test_engine.mjs`.

## Security

- All SQL is parameterized (no injection); user input is HTML-escaped on render.
- Writes (publish/edit/delete) are validated and gated by a shared password; reads are open.
- Request bodies are size-capped. Secrets are read from one `chmod 600` file, never hardcoded.

## Reliability

- The results pipeline is idempotent and matches games by unordered team-pair — robust to the
  feed flipping home/away or changing IDs.
- It fails loud: a dead or degraded feed exits non-zero and sends an alert, rather than serving
  stale data silently.
- The server runs keep-alive and reboot-proof under launchd. SQLite uses WAL with a nightly
  backup (last 7 kept); logs self-trim.

## Known trade-offs

See [ARCHITECTURE.md](ARCHITECTURE.md#known-trade-offs--roadmap).
