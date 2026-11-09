import json
import os
import re
from datetime import date, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT3 = os.path.join(os.path.dirname(HERE), "agent3_final")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def default_paths(split, variants=False):
    """Agent 3 data layout (for_agent3_v10 + kit v14.9)."""
    d = os.path.join(AGENT3, "data", split)
    v = "_variants" if variants else ""
    return {
        "patients": os.path.join(d, "input", f"patients{v}.jsonl"),
        "criteria": os.path.join(d, "reference", "criteria.jsonl"),
        "evidence": os.path.join(AGENT3, "agent3_kit", f"evidence_{split}{v}_haiku_v14_9.jsonl"),
    }


def days_before(as_of, d):
    try:
        return (date.fromisoformat(as_of) - date.fromisoformat(d[:10])).days
    except (TypeError, ValueError):
        return None


def earliest_ok(as_of, window_days):
    """A result dated on or after this day is inside the window."""
    return (date.fromisoformat(as_of) - timedelta(days=window_days)).isoformat()


def next_doc_id(patient):
    found = [m.group(1) for d in patient["documents"] for m in [re.search(r"-D(\d+)$", d["doc_id"])] if m]
    width = max([len(s) for s in found] or [2])
    return f"{patient['patient_id']}-D{str(max([int(s) for s in found] or [0]) + 1).zfill(width)}"
