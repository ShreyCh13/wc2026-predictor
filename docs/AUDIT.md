# Audit Notes

This project was reviewed with a **multi-agent audit**: several independent reviewers, each
owning a dimension (correctness, data accuracy, security, reliability, UX, data pipeline,
architecture, integration), then a synthesis pass that cross-checked and severity-ranked the
findings. The point of fanning it out is independent verification — every finding is backed by
concrete evidence (a reproduced value, a command and its output, a file and line), and anything
that couldn't be verified was dropped.

## Notable findings & fixes

| Severity | Finding | Resolution |
|----------|---------|------------|
| Critical | Results pipeline silently never updated games for teams whose feed name normalized differently from ours (USA, Bosnia, DR Congo). | Fixed the normalization so both sides produce the same token; covered by a test. |
| Critical | Write API (publish/edit/delete) was open to the internet. | Added a shared-password gate on all mutations; reads stay open. |
| High | Standings used a simplified tiebreaker. | Implemented the real FIFA order: points → goal difference → goals scored → head-to-head. |
| High | Knockout bracket wasn't scored on the leaderboard. | Added round-weighted advancement scoring (dormant until the knockouts begin). |
| High | The third-place table placement was an approximation. | Replaced with FIFA's official 495-combination Annex C lookup, parsed and verified. |
| Medium | No backups, no alerting, no version control. | Added nightly SQLite backups, ntfy alerts on feed failure, and git. |
| Medium | "Predict a game that already kicked off" was possible. | Inputs lock at kickoff. |

## What was verified as correct

Parameterized SQL (no injection), validate-before-write, WAL + locking (no races/leaks),
HTML escaping of user input, secrets read from one chmod-600 file (nothing hardcoded), the
bracket linkages (checked line-by-line against the official schedule), and the 495-row table
(every row respects the eligibility constraints).

## Method

The same audit approach is packaged as a reusable tool — see the `deep-audit` skill. It
inventories any project, picks the relevant reviewer fleet by project type, and produces one
severity-ranked report with fixes.
