"""Where the team packages are and which demo states to build.

Inside the backend repo: agent code in agents/<agent>/ (packages as they were frozen), dev data in data/dev/.
Run outputs and caches are not in git; they come from the Release zip replay_pack.zip, unpacked over this folder
(agents/agent3_judge/runs/, agents/agent5_acquire/runs/, data/dev/). See REPRODUCE.md.
"""
import os

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = BACKEND                      # paths in manifest.json are written relative to the repo root
AGENTS = os.path.join(BACKEND, "agents")

A3 = os.path.join(AGENTS, "agent3_judge")
A3_RUN = os.path.join(A3, "runs", "dev_a031_v10_kit1412_p07")        # Agent 3 dev output the "before" states use
DATA = os.path.join(BACKEND, "data", "dev")
EVIDENCE = os.path.join(DATA, "evidence", "evidence_dev_haiku_v14_12.jsonl")
EVIDENCE_LABEL = "v14.12 haiku"
A5 = os.path.join(AGENTS, "agent5_acquire")
LOOP = os.path.join(A5, "runs", "loop_SYN-0010_anthropic")            # run_loop.py output the "after" state uses
LOOP_ANSWERS = os.path.join(A5, "examples", "answers_loop_SYN-0010.jsonl")
A6 = os.path.join(AGENTS, "agent6_rank")

TRIALS = os.path.join(DATA, "reference", "trials.jsonl")
CRITERIA = os.path.join(DATA, "reference", "criteria.jsonl")
PATIENTS = os.path.join(DATA, "input", "patients.jsonl")

# (patient, state, source): "dev" = Agent 3 dev run, "loop" = the update loop after the answer
STATES = [("SYN-0010", "before", "dev"), ("SYN-0010", "after", "loop"), ("SYN-0017", "before", "dev")]

BUILD = os.path.join(BACKEND, "build")      # staged inputs and intermediate outputs, per state
OUT = os.path.join(BACKEND, "data")         # what the web page and the API serve
