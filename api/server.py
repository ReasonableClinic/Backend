"""Small REST API over the demo bundles (replay mode), plus the web page itself. Standard library only.

  python -m api.server                          # http://localhost:8000  (page from ../Healthcare-web if present)
  python -m api.server --web <web folder> --port 8000

  GET  /api/health                     {"status": "ok", "version", "built_at"}
  GET  /api/patients                   data/index.json (patients and their states)
  GET  /api/patients/<pid>             states of one patient
  GET  /api/patients/<pid>/<state>     the bundle: graph, ranking, briefing, cards, documents, trials, glossary, rules
  GET  /api/manifest                   versions, input hashes, stages, Agent 6 checks of this build
  POST /api/answers                    {"patient_id", "card_id", ...} -> the state that answer leads to

Replay mode: an answer is accepted only if it is one this build already ran through the pipeline (it is listed in a
state's meta.answers); the response is that precomputed state. Running the loop live needs the orchestrator and an
API key, so the demo replays real outputs instead (웹 확인 요청 A-1).
GET /data/<file> serves the same files, so the web demo page works unchanged against this server.

This is a local demo server (Python's http.server is not meant for production). It listens on 127.0.0.1 only, lists
no directories, takes at most 64 KB per POST, sends security headers and no CORS header unless --cors-origin is given.
With BACKEND_API_TOKEN set, /api/* and /data/* need "Authorization: Bearer <token>". A public deployment goes behind
a production server and an HTTPS reverse proxy instead (QA 4.1).
"""
import argparse
import hmac
import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from pipeline import VERSION
from pipeline.config import OUT, PROJ

SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_BODY = 64 * 1024


def _load(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return json.load(f)


class Handler(SimpleHTTPRequestHandler):
    web = None            # web page folder served at /, or None (API only)
    cors_origin = None    # one allowed origin for a page served elsewhere; None = same origin only, no CORS header
    token = None          # BACKEND_API_TOKEN, or None (local demo)
    server_version = "backend"
    sys_version = ""

    def __init__(self, *args, **kw):
        super().__init__(*args, directory=self.web or OUT, **kw)

    def log_message(self, fmt, *args):
        print("  " + fmt % args)

    # ---- headers on every response (QA S4, S6) -------------------------------------------------------------------
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        if self.cors_origin and self.headers.get("Origin") == self.cors_origin:
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def list_directory(self, path):   # QA S2: never list a folder
        self.send_error(404, "not found")
        return None

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if not self.token:
            return True
        got = self.headers.get("Authorization", "")
        return hmac.compare_digest(got.encode(), f"Bearer {self.token}".encode())

    def _bundle_file(self, pid, state):
        if not (SAFE.match(pid) and SAFE.match(state)):
            return None
        name = f"{pid}.{state}.json"
        return name if os.path.exists(os.path.join(OUT, name)) else None

    def do_OPTIONS(self):
        if not (self.cors_origin and self.headers.get("Origin") == self.cors_origin):
            return self._send(403, {"error": "origin not allowed"})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        parts = [p for p in path.split("/") if p]
        if parts[:1] in (["api"], ["data"]) and not self._authorized():
            return self._send(401, {"error": "missing or wrong bearer token"})
        if parts[:1] == ["api"]:
            return self._api_get(parts[1:])
        if parts[:1] == ["data"]:                       # the page's own data/ requests
            if len(parts) == 2 and SAFE.match(parts[1]) and parts[1].endswith(".json"):
                f = os.path.join(OUT, parts[1])
                if os.path.isfile(f):
                    with open(f, "rb") as fh:
                        body = fh.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            return self._send(404, {"error": "not found"})
        if not self.web:                               # API only: data/ is never served at / (QA S2)
            return self._send(404, {"error": "no web page on this server", "see": "/api/patients"})
        if any(p.startswith(".") for p in parts):       # no dotfiles from the web folder
            return self._send(404, {"error": "not found"})
        return super().do_GET()

    def do_HEAD(self):
        return self._send(405, {"error": "method not allowed"})

    def _api_get(self, p):
        index = _load("index.json")
        if p == ["health"]:
            return self._send(200, {"status": "ok", "version": VERSION, "built_at": index.get("built_at")})
        if p == ["patients"]:
            return self._send(200, index)
        if p == ["manifest"]:
            return self._send(200, _load("manifest.json"))
        if len(p) == 2 and p[0] == "patients":
            for pt in index["patients"]:
                if pt["patient_id"] == p[1]:
                    return self._send(200, pt)
            return self._send(404, {"error": "unknown patient"})
        if len(p) == 3 and p[0] == "patients":
            name = self._bundle_file(p[1], p[2])
            return self._send(200, _load(name)) if name else self._send(404, {"error": "unknown state"})
        return self._send(404, {"error": "unknown endpoint", "see": "/api/patients"})

    def do_POST(self):
        if self.path.split("?", 1)[0].rstrip("/") != "/api/answers":
            return self._send(404, {"error": "unknown endpoint"})
        if not self._authorized():
            return self._send(401, {"error": "missing or wrong bearer token"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad Content-Length"})
        if n < 0 or n > MAX_BODY:                       # QA S3
            self.close_connection = True
            return self._send(413, {"error": f"body larger than {MAX_BODY} bytes"})
        try:
            ans = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "body must be JSON"})
        if not isinstance(ans, dict):
            return self._send(400, {"error": "body must be a JSON object"})
        pid, cid = ans.get("patient_id"), ans.get("card_id")
        if not isinstance(pid, str) or not isinstance(cid, str) or not pid or not cid:
            return self._send(400, {"error": "need patient_id and card_id"})
        for pt in _load("index.json")["patients"]:
            if pt["patient_id"] != pid:
                continue
            for st in pt["states"]:
                for a in st.get("answers", []):
                    if a.get("card_id") == cid:
                        return self._send(200, {"mode": "replay", "state": st["state"], "answer": a,
                                                "bundle": _load(st["file"])})
        return self._send(409, {"error": "replay mode: this answer was not run through the pipeline for this build",
                                "patient_id": pid, "card_id": cid})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--web", default=os.path.join(os.path.dirname(PROJ), "Healthcare-web"), help="web page folder served at / (optional)")
    ap.add_argument("--cors-origin", help="allow this one origin (e.g. http://localhost:5173) when the page is served "
                                          "elsewhere; default: no CORS header (same origin only)")
    a = ap.parse_args()
    if not os.path.exists(os.path.join(OUT, "index.json")):
        raise SystemExit("no data/index.json: run  python -m pipeline.build_demo  first")
    Handler.web = a.web if os.path.isfile(os.path.join(a.web, "index.html")) else None
    Handler.cors_origin = a.cors_origin
    Handler.token = os.environ.get("BACKEND_API_TOKEN") or None
    print(f"API  http://localhost:{a.port}/api/patients" + ("  (bearer token required)" if Handler.token else ""))
    print(f"page http://localhost:{a.port}/  ({'web page folder found' if Handler.web else 'none, API only'})")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
