#!/usr/bin/env python3
"""WC2026 results ingestion pipeline.

Pulls finished/live scores from ESPN's public JSON scoreboard (no key) and updates the
canonical fixtures (group stage -> `matches`) and knockout results (-> `ko_results`).
Fixtures are never created/renamed here; matching is by unordered team-pair (unique within
a stage), routed to group vs knockout by ESPN date.

House conventions: idempotent writes, validate before write, fail LOUD + notify on feed death.
"""
import json, os, sqlite3, sys, time, unicodedata, datetime
import urllib.request, urllib.parse, urllib.error

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "data", "wc2026.db")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={}"

# full tournament window (US dates). Group stage ends Jun 27; knockouts Jun 28 - Jul 19.
DATES = [f"202606{d:02d}" for d in range(11, 31)] + [f"202607{d:02d}" for d in range(1, 20)]
GROUP_CUTOFF = "2026-06-27"   # ESPN date <= this and a known group pair => group game

# ESPN display name -> our canonical token. VALUES are already normalized (lowercase,
# alnum) so both sides of the team-pair match collapse to the same string.
ALIASES = {
    "unitedstates": "usa",
    "bosniaherzegovina": "bosnia",
    "congodr": "drcongo",
    "ivorycoast": "ivorycoast",
    "cotedivoire": "ivorycoast",
}


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = "".join(c for c in s if c.isalnum())
    return ALIASES.get(s, s)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def env(key, default=None):
    """Read a key from the one house secrets file, else process env."""
    path = os.path.expanduser("~/.config/agents/.env")
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get(key, default)


def notify(msg):
    """Best-effort alert via ntfy (topic from secrets). Never raises."""
    topic = env("NTFY_TOPIC")
    if not topic:
        return
    url = env("NTFY_URL", "https://ntfy.sh").rstrip("/") + "/" + topic
    try:
        req = urllib.request.Request(url, data=msg.encode("utf-8"),
                                     headers={"Title": "WC2026 pipeline", "Priority": "high"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        sys.stderr.write("notify failed (non-fatal)\n")


def fetch_date(d):
    """Return (events, ok). ok=False means a real HTTP/transport error (not just empty)."""
    req = urllib.request.Request(ESPN.format(d), headers={"User-Agent": "wc2026-pipeline/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status != 200:
                    return [], False
                return json.loads(r.read()).get("events", []), True
        except urllib.error.HTTPError as e:
            sys.stderr.write(f"WARN: {d} HTTP {e.code}\n")
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** attempt); continue
            return [], False
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 2:
                sys.stderr.write(f"WARN: {d} transport error: {e}\n")
                return [], False
            time.sleep(2 ** attempt)
    return [], False


def parse_event(e):
    """-> (pair_set, home_norm, hs, as, state, iso_date) or None."""
    try:
        comp = e["competitions"][0]
        cs = comp["competitors"]
        h = next(c for c in cs if c["homeAway"] == "home")
        a = next(c for c in cs if c["homeAway"] == "away")
        hn, an = norm(h["team"]["displayName"]), norm(a["team"]["displayName"])
        state = e["status"]["type"]["state"]  # pre | in | post
        hs = a_s = None
        if state in ("in", "post"):
            hs = int(h["score"]) if str(h.get("score", "")).strip() != "" else None
            a_s = int(a["score"]) if str(a.get("score", "")).strip() != "" else None
        return frozenset((hn, an)), hn, an, hs, a_s, state, e.get("date", "")[:10]
    except (KeyError, StopIteration, ValueError, TypeError):
        return None


def main():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000;")
    # defensive schema (server owns it, but keep the pipeline self-sufficient)
    con.execute("""CREATE TABLE IF NOT EXISTS ko_results (
        pair TEXT PRIMARY KEY, team_a TEXT, team_b TEXT, winner TEXT,
        home_score INTEGER, away_score INTEGER, kickoff_iso TEXT, espn_date TEXT, updated_at TEXT);""")
    cols = {r[1] for r in con.execute("PRAGMA table_info(matches)")}
    if "kickoff_iso" not in cols:
        con.execute("ALTER TABLE matches ADD COLUMN kickoff_iso TEXT")
    con.commit()

    fixtures = con.execute("SELECT * FROM matches").fetchall()
    group_pairs = {frozenset((norm(r["home"]), norm(r["away"]))): r for r in fixtures}

    total_events, http_failures = 0, 0
    updated, finalized = 0, []
    seen_pairs = set()

    for d in DATES:
        events, ok = fetch_date(d)
        if not ok:
            http_failures += 1
            continue
        for e in events:
            parsed = parse_event(e)
            if not parsed:
                continue
            total_events += 1
            pair, hn, an, hs, a_s, state, iso = parsed
            if pair in seen_pairs and state != "post":
                continue
            grp_row = group_pairs.get(pair)
            is_group = grp_row is not None and (iso == "" or iso <= GROUP_CUTOFF)

            if is_group:
                r = grp_row
                # always refresh kickoff time; persist score only when final
                set_parts, args = ["kickoff_iso=?"], [iso or r["kickoff_iso"]]
                if state == "post" and hs is not None and a_s is not None:
                    my_hs, my_as = (hs, a_s) if hn == norm(r["home"]) else (a_s, hs)
                    if not (r["status"] == "final" and r["home_score"] == my_hs and r["away_score"] == my_as):
                        set_parts += ["home_score=?", "away_score=?", "status='final'"]
                        args += [my_hs, my_as]
                        finalized.append(f'{r["grp"]}: {r["home"]} {my_hs}-{my_as} {r["away"]}')
                        updated += 1
                        seen_pairs.add(pair)
                args += [now(), r["grp"], r["idx"]]
                con.execute(f"UPDATE matches SET {','.join(set_parts)}, updated_at=? WHERE grp=? AND idx=?", args)
            elif state == "post" and hs is not None and a_s is not None:
                # knockout result
                team_a, team_b = sorted((hn, an))
                winner = hn if hs > a_s else (an if a_s > hs else "")  # KO can't truly draw, but guard
                con.execute(
                    "INSERT INTO ko_results(pair,team_a,team_b,winner,home_score,away_score,kickoff_iso,espn_date,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(pair) DO UPDATE SET winner=excluded.winner,"
                    "home_score=excluded.home_score,away_score=excluded.away_score,kickoff_iso=excluded.kickoff_iso,updated_at=excluded.updated_at",
                    ("|".join(sorted((hn, an))), team_a, team_b, winner, hs, a_s, iso, iso, now()))
                seen_pairs.add(pair)
        time.sleep(0.15)
    con.commit()
    con.close()

    # FAIL LOUD: a totally empty feed means ESPN changed/blocked us.
    if total_events == 0:
        sys.stderr.write("FATAL: ESPN returned 0 events across all dates — feed down/changed?\n")
        notify("WC2026: ESPN feed returned 0 events — results pipeline is blind.")
        sys.exit(1)
    if http_failures >= len(DATES) // 2:
        sys.stderr.write(f"FATAL: {http_failures}/{len(DATES)} dates failed HTTP — degraded feed.\n")
        notify(f"WC2026: {http_failures}/{len(DATES)} ESPN dates failed — results may be stale.")
        sys.exit(1)

    print(f"[{now()}] events_seen={total_events} http_failures={http_failures} matches_updated={updated}")
    for line in finalized:
        print("  ✓", line)


if __name__ == "__main__":
    main()
