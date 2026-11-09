"""Regression check: numeric hints taken from inside ratio expressions (X/Y ratio, X:Y)."""
import json, re, sys
sys.path.insert(0, "agent2")
import rules as R
from extract import Extractor, load_concepts
from segment import units
ex = Extractor(load_concepts("agent2/concepts.json"))
RATIO = re.compile(r"\w+\s*/\s*\w+[^.;\n]{0,15}?ratio|\bratio\b|\b\w+/\w+\b(?=\s+\d)", re.I)
bad = 0
for p in map(json.loads, open("data/dev/input/patients.jsonl")):
    for d in p["documents"]:
        for u in units(d["text"]):
            t = d["text"][slice(*u["span"])]
            for key, val, unit, _ in R.numeric_values(t, ex.numeric):
                m = re.search(r"(protein|albumin|BUN|urea|FEV1|AST|ALT|LDL|HDL|cholesterol)\s*/\s*\w+|/\s*creatinine|creatinine\s+ratio", t, re.I)
                if m and key in ("creatinine", "albumin", "alt", "ast", "total_cholesterol", "pulmonary_function", "hdl"):
                    bad += 1
                    print(f"{key}={val} {unit} | {t[:90]}")
print("suspicious:", bad)
