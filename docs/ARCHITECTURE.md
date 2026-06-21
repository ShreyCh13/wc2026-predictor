# Architecture

## System at a glance

```
                ESPN public JSON feed (no key)
                          │
            update_results.py  (launchd, every 30 min)
            • normalize team names  • match by team-pair
            • idempotent UPSERT     • fail-loud + ntfy alert
                          │
                          ▼
                 SQLite  (WAL, nightly backup)
        ┌─────────────┬───────────────┬──────────────┐
        │  matches    │  ko_results   │ wc_scenarios │
        │ (fixtures + │ (knockout     │ (friends'    │
        │  live scores)│  winners)    │  brackets)   │
        └─────────────┴───────────────┴──────────────┘
                          │
              server.py  (stdlib HTTP, 127.0.0.1:8790)
        GET /api/matches · /api/ko_results · /api/scenarios
        POST/PUT/DELETE /api/scenarios  (password-gated)
                          │
            Tailscale Funnel  (TLS, public :8443)
                          │
                          ▼
          index.html  — single-page app in the browser
   standings · FIFA tiebreakers · 495-row third-place table ·
   clickable bracket · live leaderboard scoring
```

## Components

| File | Role |
|------|------|
| `index.html` | The entire front end — UI, the prediction/bracket engine, the FIFA allocation table, and the API client, in one self-contained file. |
| `server.py` | Zero-dependency HTTP server + SQLite store. Serves the page and a small JSON API. |
| `update_results.py` | The results pipeline. Pulls finished scores from ESPN and updates the database. |
| `fixtures_seed.json` | The 72 group-stage fixtures, used to seed the database once. |
| `deploy/` | launchd service definitions + a one-command deploy script. |
| `tests/` | Headless tests for the engine and the FIFA table. |

## Data flow & sources of truth

- **Results** flow ESPN → `matches`/`ko_results` (database) → `/api/...` → browser. The
  database is the single source of truth; the browser never invents scores.
- **Predictions** live in the browser (auto-saved locally) until *published*, at which point
  they're stored in `wc_scenarios` and shared with everyone.
- **Scoring** happens in the browser, comparing each published bracket to the live results.

## Design decisions (and why)

- **One self-contained `index.html`.** No build step, no bundler, no framework. For a single-
  screen app deployed by copying one file, this removes an entire class of build/version-skew
  problems and stays trivially hostable and forkable. The cost is testability, which the
  `tests/` harness recovers by evaluating the page script in a DOM stub.
- **Standard-library Python, no dependencies.** Nothing to `pip install`, nothing to break on
  a version bump, and the always-on server has no third-party attack surface. Appropriate for
  ~tens of users on a personal host.
- **SQLite with WAL + nightly backups.** A single-file database that's safe under concurrent
  reads/writes and trivially backed up. No database server to operate.
- **Match results by *team-pair*, not by feed-specific IDs.** Group-stage pairings are unique,
  so matching `frozenset({home, away})` is robust to the feed flipping home/away or changing
  IDs. Team names are normalized identically on both sides (see "known trade-offs").
- **The 495-row FIFA third-place table is precomputed data, not runtime logic.** FIFA's Annex
  C allocation (which 3rd-place team fills which Round-of-32 slot) is a published lookup table;
  computing it live would be bug-prone. It's parsed from Wikipedia's raw wikitext and verified
  (every row respects the eligibility constraints — see `tests/`).
- **Tailscale Funnel for hosting.** Free, TLS-terminated public access from a machine behind
  NAT, with no inbound ports opened on the router.

## Reliability

- Server runs under launchd with `KeepAlive` (crash-restart) + `RunAtLoad` (reboot-proof).
- The pipeline is idempotent and **fails loud**: a dead/degraded feed exits non-zero and
  pings ntfy, rather than silently serving stale data.
- Writes are validated before touching the database and gated by a shared password.
- Nightly SQLite backup keeps the last 7 copies; logs self-trim.

## Known trade-offs & roadmap

Honest list of things a reviewer would (rightly) flag:

- **Two normalizers must stay in lockstep.** `update_results.py:norm()` and
  `index.html:normTeam()` generate the two halves of the knockout-results key. They share an
  alias map and are covered by a test, but the cleanest fix is to have the server emit the
  canonical token so the client never re-derives it.
- **Two bracket resolvers.** The live engine and the "what actually happened" resolver encode
  the same linkage logic twice. Unifying them (parameterizing one `resolve()` to take its state
  as an argument) would remove the duplication and a global-mutation foot-gun, and make the
  whole engine pure/unit-testable. Deliberately deferred while the app is live during the
  tournament — refactoring a running hot path mid-event isn't worth the risk.
- **Knockout scoring** is built and unit-tested but can't be verified end-to-end until real
  knockout games exist (June 28).
