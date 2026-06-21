#!/usr/bin/env python3
"""WC2026 Knockout Predictor — shared scenarios server.

Stdlib-only (no deps). Serves the single-page app and a JSON API backed by SQLite
so friends can list / add / edit / delete bracket scenarios from anywhere.

House conventions: SQLite + WAL, idempotent schema, validate-before-write, fail loud.
"""
import json, os, re, sqlite3, sys, uuid, datetime, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "data", "wc2026.db")
INDEX = os.path.join(APP_DIR, "index.html")
SEED = os.path.join(APP_DIR, "fixtures_seed.json")
PORT = int(os.environ.get("WC_PORT", "8790"))

NAME_MAX, AUTHOR_MAX, DATA_MAX = 60, 40, 60000
_db_lock = threading.Lock()


def _env(key, default=None):
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


# if set, POST/PUT/DELETE require header  X-WC-Key: <token>
WRITE_TOKEN = _env("WC_WRITE_TOKEN")


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con


def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS wc_scenarios (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                author     TEXT,
                data       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        # canonical fixtures: rows are fixed; only scores/status get updated by the pipeline
        con.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                grp        TEXT NOT NULL,
                idx        INTEGER NOT NULL,
                home       TEXT NOT NULL,
                away       TEXT NOT NULL,
                kickoff    TEXT,
                home_score INTEGER,
                away_score INTEGER,
                status     TEXT NOT NULL DEFAULT 'scheduled',
                kickoff_iso TEXT,
                updated_at TEXT,
                PRIMARY KEY (grp, idx)
            );
        """)
        # migration for DBs created before kickoff_iso existed
        cols = {r[1] for r in con.execute("PRAGMA table_info(matches)")}
        if "kickoff_iso" not in cols:
            con.execute("ALTER TABLE matches ADD COLUMN kickoff_iso TEXT")
        # knockout results (filled by the pipeline; team tokens are normalized lowercase)
        con.execute("""
            CREATE TABLE IF NOT EXISTS ko_results (
                pair       TEXT PRIMARY KEY,
                team_a     TEXT, team_b TEXT, winner TEXT,
                home_score INTEGER, away_score INTEGER,
                kickoff_iso TEXT, espn_date TEXT, updated_at TEXT
            );
        """)
        con.commit()
        seed_matches(con)


def seed_matches(con):
    """One-time seed of the 72 group fixtures (idempotent: only if table empty)."""
    if con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]:
        return
    with open(SEED) as f:
        data = json.load(f)
    ts = now()
    for grp, arr in data.items():
        for m in arr:
            status = "final" if m.get("hs") is not None else "scheduled"
            con.execute(
                "INSERT OR IGNORE INTO matches(grp,idx,home,away,kickoff,home_score,away_score,status,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (grp, m["idx"], m["home"], m["away"], m["date"], m.get("hs"), m.get("as"), status, ts))
    con.commit()
    sys.stderr.write("seeded matches table from fixtures_seed.json\n")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def row_to_obj(r):
    return {
        "id": r["id"], "name": r["name"], "author": r["author"],
        "data": json.loads(r["data"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def validate(payload):
    """Return (clean_dict, error_str). Validate BEFORE touching the DB."""
    if not isinstance(payload, dict):
        return None, "bad payload"
    name = (payload.get("name") or "").strip()
    author = (payload.get("author") or "").strip()
    data = payload.get("data")
    if not name or len(name) > NAME_MAX:
        return None, f"name must be 1-{NAME_MAX} chars"
    if len(author) > AUTHOR_MAX:
        return None, f"author max {AUTHOR_MAX} chars"
    if not isinstance(data, dict):
        return None, "data must be an object"
    data_json = json.dumps(data, separators=(",", ":"))
    if len(data_json) > DATA_MAX:
        return None, "scenario too large"
    return {"name": name, "author": author, "data_json": data_json}, None


class H(BaseHTTPRequestHandler):
    server_version = "wc2026/1.0"

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # never let the funnel/edge/browser cache app or API responses
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        # permissive CORS so the page works regardless of host/port
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n > DATA_MAX + 2000:
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return None

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _authed(self):
        return (not WRITE_TOKEN) or (self.headers.get("X-WC-Key") == WRITE_TOKEN)

    def _too_big(self):
        try:
            return int(self.headers.get("Content-Length", "0") or "0") > DATA_MAX + 2000
        except ValueError:
            return True

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, b"index.html missing", "text/plain")
            return
        if self.path == "/api/health":
            self._json(200, {"ok": True, "auth_required": bool(WRITE_TOKEN)})
            return
        if self.path == "/api/ko_results":
            with _db_lock, db() as con:
                rows = con.execute("SELECT pair, winner FROM ko_results WHERE winner != ''").fetchall()
            self._json(200, {r["pair"]: r["winner"] for r in rows})
            return
        if self.path == "/api/scenarios":
            with _db_lock, db() as con:
                rows = con.execute(
                    "SELECT * FROM wc_scenarios ORDER BY updated_at DESC").fetchall()
            self._json(200, [row_to_obj(r) for r in rows])
            return
        if self.path == "/api/matches":
            with _db_lock, db() as con:
                rows = con.execute("SELECT * FROM matches ORDER BY grp, idx").fetchall()
            out = {}
            for r in rows:
                out.setdefault(r["grp"], []).append(
                    [r["home"], r["away"], r["home_score"], r["away_score"], r["kickoff"], r["status"], r["kickoff_iso"]])
            self._json(200, out)
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/scenarios":
            return self._send(404, b"not found", "text/plain")
        if not self._authed():
            return self._json(401, {"error": "wrong or missing password"})
        if self._too_big():
            return self._json(413, {"error": "scenario too large"})
        payload = self._body()
        clean, err = validate(payload) if payload is not None else (None, "bad json")
        if err:
            return self._json(400, {"error": err})
        sid = uuid.uuid4().hex
        ts = now()
        with _db_lock, db() as con:
            con.execute(
                "INSERT INTO wc_scenarios(id,name,author,data,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (sid, clean["name"], clean["author"], clean["data_json"], ts, ts))
            con.commit()
        self._json(201, {"id": sid})

    def do_PUT(self):
        m = re.match(r"^/api/scenarios/([0-9a-f]{32})$", self.path)
        if not m:
            return self._send(404, b"not found", "text/plain")
        if not self._authed():
            return self._json(401, {"error": "wrong or missing password"})
        if self._too_big():
            return self._json(413, {"error": "scenario too large"})
        sid = m.group(1)
        payload = self._body()
        clean, err = validate(payload) if payload is not None else (None, "bad json")
        if err:
            return self._json(400, {"error": err})
        with _db_lock, db() as con:
            cur = con.execute(
                "UPDATE wc_scenarios SET name=?,author=?,data=?,updated_at=? WHERE id=?",
                (clean["name"], clean["author"], clean["data_json"], now(), sid))
            con.commit()
            if cur.rowcount == 0:
                return self._json(404, {"error": "not found"})
        self._json(200, {"id": sid})

    def do_DELETE(self):
        m = re.match(r"^/api/scenarios/([0-9a-f]{32})$", self.path)
        if not m:
            return self._send(404, b"not found", "text/plain")
        if not self._authed():
            return self._json(401, {"error": "wrong or missing password"})
        with _db_lock, db() as con:
            cur = con.execute("DELETE FROM wc_scenarios WHERE id=?", (m.group(1),))
            con.commit()
            if cur.rowcount == 0:
                return self._json(404, {"error": "not found"})
        self._json(200, {"ok": True})


def main():
    init_db()
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError as e:
        sys.stderr.write(f"FATAL: cannot bind 127.0.0.1:{PORT}: {e}\n")
        sys.exit(1)
    sys.stderr.write(f"wc2026 server listening on 127.0.0.1:{PORT}, db={DB_PATH}\n")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
