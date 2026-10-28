"""Load API keys and settings from a .env file, so keys never go on the command line or into code.

    from common.env_setup import load_env
    load_env()                      # once, at the start of a run.py

Search order (first file found wins): $ENV_FILE, ./.env (the folder you run from), <repo root>/.env.
Values already set in the shell are kept (a one-off `export X=...` still overrides the file).
Uses python-dotenv when it is installed, otherwise a small built-in parser (KEY=value lines, # comments, quotes).
Moved from agent2 v14.12 (agent2/env_setup.py), generalised for every agent.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loaded = None


def _parse(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        elif " #" in v:                      # inline comment after an unquoted value
            v = v.split(" #", 1)[0].rstrip()
        out[k] = v
    return out


def load_env():
    """Load the first .env found into os.environ (existing variables win). Returns the path used, or None."""
    global _loaded
    if _loaded is not None:
        return _loaded or None
    cands = [os.environ.get("ENV_FILE"), os.path.join(os.getcwd(), ".env"), os.path.join(REPO_ROOT, ".env")]
    path = next((os.path.abspath(p) for p in cands if p and os.path.isfile(p)), None)
    _loaded = path or ""
    if not path:
        return None
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
    except ImportError:
        for k, v in _parse(path).items():
            if v != "":                      # an empty value in .env (KEY=) is skipped, so it never blanks a key
                os.environ.setdefault(k, v)
    return path


def require(*names):
    """Stop with a clear message when a key is missing (call after load_env)."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"STOP: {', '.join(missing)} not set. Put it in .env (see .env.example) or export it.")


def masked(name):
    """'sk-or-…3f9a' style hint for logs; never print a full key."""
    v = os.environ.get(name) or ""
    return f"{v[:6]}…{v[-4:]}" if len(v) > 12 else ("set" if v else "not set")
