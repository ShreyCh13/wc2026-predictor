# ⚽ World Cup 2026 — Predictor & Leaderboard

A self-updating prediction game for the 2026 World Cup. Predict scorelines and fill out the
knockout bracket, publish it, and climb a **live leaderboard** that scores everyone against
real match results as they come in — no manual updating, ever.

**🔗 Live:** https://shrey-mini.tail005d47.ts.net:8443 &nbsp;·&nbsp; **License:** MIT &nbsp;·&nbsp; **Tests:** `node tests/test_engine.mjs` (14 passing)

> Self-hosted on a Mac mini behind Tailscale. Zero third-party dependencies. One HTML file,
> one Python server, one SQLite database.

---

## What it does

- **Predict** the score of every upcoming match. Standings recompute instantly using the real
  FIFA tiebreakers (points → goal difference → goals scored → head-to-head).
- **Fill the bracket** — Round of 32 to the final — including the 48-team format's *eight best
  third-placed teams*, placed by FIFA's official allocation table.
- **Compete** — publish your bracket to a shared board. As real games finish, every bracket is
  scored automatically (**5 points for an exact score, 2 for the right winner**, plus
  round-weighted points for correctly predicting who advances). The board is a ranked
  leaderboard with your standing, your name, and per-game "you predicted X, actual was Y."
- **Stays current on its own** — a pipeline pulls finished scores every 30 minutes; inputs lock
  at kickoff so nobody predicts a game that already started.

## How it works

```
ESPN public JSON feed ──▶ update_results.py (launchd, 30 min) ──▶ SQLite ──▶ server.py (stdlib HTTP)
                          normalize · match by team-pair          (WAL +      JSON API + static page
                          idempotent · fail-loud + alert           backups)         │
                                                                                    ▼
                                                            Tailscale Funnel (TLS) ──▶ index.html
                                                       standings · FIFA tiebreakers · 495-row
                                                       third-place table · bracket · live scoring
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and the trade-offs.

## Engineering highlights

- **Source-verified accuracy.** The bracket linkages were checked line-by-line against the
  official match schedule, and the third-place placement uses FIFA's **495-combination Annex C
  allocation table**, parsed from primary sources and validated by tests (every row respects the
  eligibility constraints).
- **Self-healing data pipeline.** Pulls from a public feed with no API key; matches games by
  *unordered team-pair* (robust to the feed flipping home/away or changing IDs); idempotent
  writes; **fails loud** with an alert instead of silently serving stale data.
- **Zero dependencies.** Standard-library Python and a single hand-written HTML file — nothing to
  `pip install`, no build step, no framework, minimal attack surface.
- **Production hygiene on a personal host.** launchd keep-alive + reboot-proof, nightly SQLite
  backups, password-gated writes, secrets in one `chmod 600` file (never in code), self-trimming
  logs.
- **Tested headlessly.** The engine and the FIFA table are covered by tests that evaluate the
  page script in a DOM stub — no browser required.
- **Reviewed by a multi-agent audit.** Independent reviewers per dimension, cross-checked and
  severity-ranked. Findings and fixes in [`docs/AUDIT.md`](docs/AUDIT.md).

## Tech stack

| Layer | Choice | Why |
|------|--------|-----|
| Front end | One self-contained `index.html` (vanilla JS/CSS) | No build step; trivially hostable and forkable |
| Backend | Python standard library (`http.server`) | Zero dependencies; nothing to break on a version bump |
| Storage | SQLite (WAL) | Single-file, concurrent-safe, trivially backed up |
| Scheduling | launchd | Keep-alive + reboot-proof, native to macOS |
| Hosting | Tailscale Funnel | Free public TLS from a machine behind NAT |
| Data | ESPN public JSON feed | Live scores, no API key |

## Run it locally

```bash
python3 server.py          # serves http://127.0.0.1:8790
# open http://127.0.0.1:8790 in a browser
python3 update_results.py  # pull the latest scores into the database
node tests/test_engine.mjs # run the test suite
```

No installation step — it's the Python standard library and one HTML file.

## Deploy

```bash
deploy/deploy.sh           # copies the app to the host and (re)loads the launchd services
```

## Project structure

```
.
├── index.html              # the entire front end + prediction engine
├── server.py               # stdlib HTTP server + SQLite API
├── update_results.py       # results ingestion pipeline (ESPN → SQLite)
├── fixtures_seed.json      # the 72 group-stage fixtures
├── tests/test_engine.mjs   # headless tests for the engine + FIFA table
├── deploy/                 # launchd services + one-command deploy
└── docs/                   # architecture + audit notes
```

## Related project

**[Gut Check](#)** — a companion Telegram bot for the same World Cup that journals your betting
*reads* before kickoff and grades them at full time to surface your real edge. Where this project
is the *social* game (a friends' bracket leaderboard), Gut Check is the *private* analyst. Both
run on the same host and share the same tournament data.

---

*Built during the 2026 World Cup. The prediction engine, the data pipeline, and the FIFA
allocation logic are the interesting parts — start there.*
