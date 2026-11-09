"""Load API keys and settings from a .env file, so keys never go on the command line or into code.

Copied from Agent 2 v14.10 (agent2/env_setup.py, team proposal 5차 회의) for Agent 3 a3-0.3.1.
Search order (first file found wins): $AGENT3_ENV_FILE, ./.env (the folder you run from), <agent3 package root>/.env.
Values already set in the shell are kept (a one-off `export X=...` still overrides the file).
Uses python-dotenv when it is installed, otherwise a small built-in parser (KEY=value lines, # comments, quotes).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
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
    cands = [os.environ.get("AGENT3_ENV_FILE"), os.path.join(os.getcwd(), ".env"), os.path.join(HERE, "..", ".env")]
    path = next((os.path.abspath(p) for p in cands if p and os.path.isfile(p)), None)
    _loaded = path or ""
    if not path:
        return None
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
    except ImportError:
        for k, v in _parse(path).items():
            os.environ.setdefault(k, v)
    return path


def masked(name):
    """'sk-or-…3f9a' style hint for logs; never print a full key."""
    v = os.environ.get(name) or ""
    return f"{v[:6]}…{v[-4:]}" if len(v) > 12 else ("set" if v else "not set")
