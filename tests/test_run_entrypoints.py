"""Pipeline entry points: frozen versions, and the input/output keys run_pipeline passes between stages."""
import importlib, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pipeline.run_pipeline import MODULES, ORDER  # noqa: E402

VERSIONS = {"agent1": "agent1 (캐시 200)", "agent2": "v14.12", "agent3": "a3-0.3.1 + p07 + claude-sonnet-5-5",
            "agent4": "v2", "agent5": "a5u-0.2.0 + a5j-0.3.1", "agent6": "a6-0.4.14"}


class EntryPoints(unittest.TestCase):
    def test_versions(self):
        for agent, mod in MODULES.items():
            self.assertEqual(importlib.import_module(mod).VERSION, VERSIONS[agent], agent)

    def test_keys_chain(self):
        # every stage in ORDER gets its required inputs from the pipeline files or an earlier stage
        have = {"patients", "pairs", "trials", "criteria", "evidence", "concepts"}
        for agent in ORDER:
            mod = importlib.import_module(MODULES[agent])
            self.assertFalse(set(mod.INPUTS) - have, f"{agent} needs {set(mod.INPUTS) - have}")
            have |= set(mod.OUTPUTS)
        a5 = importlib.import_module(MODULES["agent5"])
        self.assertNotIn("patients", a5.OUTPUTS)      # must not replace the pipeline's patients file


if __name__ == "__main__":
    unittest.main()
