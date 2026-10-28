"""Skeleton rules: every agent folder has README.md and run.py with run(inputs, out_dir, config); common/ works
without optional packages; no key values in .env.example; manifest catches mixed evidence versions."""
import importlib, inspect, json, os, re, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def agent_dirs():
    for base, dirs, files in os.walk(os.path.join(ROOT, "agents")):
        if "run.py" in files:
            yield base


class Skeleton(unittest.TestCase):
    def test_agent_folders(self):
        found = list(agent_dirs())
        self.assertGreaterEqual(len(found), 6)
        for d in found:
            rel = os.path.relpath(d, ROOT)
            self.assertTrue(os.path.isfile(os.path.join(d, "README.md")), f"{rel}: README.md missing")
            mod = importlib.import_module(rel.replace(os.sep, ".") + ".run")
            self.assertTrue(callable(getattr(mod, "run", None)), f"{rel}: run() missing")
            self.assertEqual(list(inspect.signature(mod.run).parameters)[:2], ["inputs", "out_dir"], rel)
            for name in ("AGENT", "VERSION", "INPUTS"):
                self.assertTrue(hasattr(mod, name), f"{rel}: {name} missing")

    def test_env_example_has_no_values(self):
        for line in open(os.path.join(ROOT, ".env.example"), encoding="utf-8"):
            m = re.match(r"\s*([A-Z_]*(?:KEY|SECRET)[A-Z_]*)\s*=\s*(\S*)", line)
            if m:
                self.assertEqual(m.group(2), "", f".env.example must not hold a value for {m.group(1)}")

    def test_env_setup_parser(self):
        from common import env_setup
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, ".env")
            open(p, "w").write('# c\nexport A_KEY="x y"\nB_KEY=abc # note\nC_KEY=\n')
            self.assertEqual(env_setup._parse(p), {"A_KEY": "x y", "B_KEY": "abc", "C_KEY": ""})

    def test_tracing_off_is_noop(self):
        from common.tracing import Tracer
        old = {k: os.environ.pop(k, None) for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")}
        try:
            tr = Tracer.create(agent="agent3")
            self.assertFalse(tr.enabled)
            tr.llm(key="SYN-0001", name="x").end(output="y")      # chained calls do nothing
            tr.result(key="SYN-0001", scores={"n": 1})
            tr.finish()
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v

    def test_manifest_catches_mixed_versions(self):
        from pipeline.manifest import Manifest
        with tempfile.TemporaryDirectory() as t:
            ev, out = os.path.join(t, "ev.jsonl"), os.path.join(t, "out.jsonl")
            open(ev, "w").write(json.dumps({"evidence_id": "P-EV001"}) + "\n")
            open(out, "w").write(json.dumps({"criteria": [{"evidence_ids": ["P-EV001"]}]}) + "\n")
            m = Manifest("r", t)
            self.assertEqual(m.check_ids("agent3", out, ev), 1)
            open(out, "w").write(json.dumps({"criteria": [{"evidence_ids": ["P-EV999"]}]}) + "\n")
            with self.assertRaises(SystemExit):
                m.check_ids("agent3", out, ev)


if __name__ == "__main__":
    unittest.main()
