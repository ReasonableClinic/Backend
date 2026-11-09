---
name: evidence-extraction-agent
description: Build, run, or evaluate Agent 2 (Evidence Extraction) of the patient-trial matching system, which turns patient records (② format) into evidence objects (③ format). Use when working on evidence extraction, span locating, negation and family history handling, or scoring against gold_evidence.
---

# Agent 2: Evidence Extraction

Patient record (②) in, evidence objects (③) out, for the multi-agent clinical trial matching system. Agent 3 (Eligibility Reasoner) judges trial criteria from these evidence objects only, so missing evidence becomes a wrong UNKNOWN downstream: recall matters most.

## Read first

1. `AGENT2_BRIEF.md`: project context, interfaces with agents 1/3/4/5, data, design draft, progress checklist, open questions. Update its checklist (section 9) as work progresses.
2. `common_format_v0.5.md` sections 4 (②), 5 (③), 6 (④ gold_evidence), 8 (shared rules).
3. `claude/AGENT2_OUTPUT_FOR_AGENT3.md`: what Agent 3 receives (kit files, fields, quality, lookup).

## Package layout

```
SKILL.md, AGENT2_BRIEF.md, common_format_v0.5.md
code/        gold_lib.py (locate, call_llm, parse_json), fill_gold_evidence.py (concept/value prompt + normalize),
             check_concepts.py (concepts.json + units), eval_evidence.py (scorer), eval_concepts.py (concept / numeric check)
agent2/      extract.py (rules), llm_layer.py (Haiku 4.5 batch), evidence_index.py (Agent 3 lookup), update.py,
             carry_ids.py, postfix.py, preflight_inputs.py, release.py, RUN_LOCAL.md, RUN_TEST.md, concepts.json (+ concepts_agent2.json)
data/dev/    input/patients.jsonl, reference/ (①-a), reference_1b/ (①-b), gold/gold.jsonl  (develop here)
data/test/   input/, reference/, reference_1b/ only                                    (final evaluation once)
```

Run outputs go under `runs/<name>/evidence.jsonl` (one ③ object per line); kit files for Agent 3 under `agent3_kit/`.

## Non-negotiable rules

- No record, no evidence. Make `value: false` evidence only when the record explicitly denies ("No prior malignancy", "NKDA", "never smoker"). Never infer absence from silence.
- Spans are exact: `source.text == document["text"][span[0]:span[1]]`. Re-locate every LLM quote with `gold_lib.locate`; drop or retry quotes that cannot be found. No "..." in quotes.
- Dates: `observed_date` = when the fact happened. Default to the document date; resolve relative dates ("3 days ago") from the document date; masked or impossible dates (TREC `[**...**]`) -> `null`. Never use today's date; `as_of` is the reference (synthetic 2026-10-01, TREC 2021-04-27).
- `certainty`: tests/pathology/imaging `confirmed`, patient statements `reported`, "suspected / possible / features of / rule out / under work-up" `suspected`.
- `subject: "family"` for relatives' history.
- Plans and discussed options ("Options discussed", "plan to start", "consider") are not treatments received.
- Concept keys only from the team's ①-b `agent2/concepts.json` (138 keys) plus Agent 2's overlay `concepts_agent2.json`. Numeric values converted to the concept's default unit. (`concepts_provisional.json` is the pre-①-b list, kept for old runs only.)
- Extract facts only. Do not output eligibility judgments; that is Agent 3.
- Test blind: develop and tune on `data/dev`, TREC and TrialGPT only. Run `data/test` once with a frozen version (after Agent 3 is frozen, procedure `agent2/RUN_TEST.md`); do not tune after seeing test results. Never put `id_map*.json`, `review.csv` (base ids) or gold files into agent input.

## Workflow

1. Plan: collect the concepts needed by the candidate trials (①-b `concept`, `answerable_by`), else the default list. Log the plan per patient (it is shown in the demo as "the agent planned what to look for").
2. Extract: rules for labs (aliases + number + unit near the alias), LLM (JSON output, short verbatim quotes) for conditions, drugs, procedures, negations, family history, suspected vs confirmed.
3. Locate spans, resolve dates, convert units, compute derived values with code (eGFR CKD-EPI, BMI, age).
4. Self-check: span match, value range, date <= as_of, duplicates. Re-extract only the failures (max 2 retries), log what was retried.
5. Update loop: on Agent 4 feedback or Agent 5 new information (added as a `patient_interview` document), re-extract only the affected document or concept (`agent2/update.py`).

## Evaluate

```
python3 code/eval_evidence.py --gold data/dev/gold/gold.jsonl --pred runs/dev_v1/evidence.jsonl --patients data/dev/input/patients.jsonl --by doc_type
```

Report: recall (any overlap, main), recall at IoU 0.5, predictions per patient, concept and value agreement (gold concepts are filled since dev_v5), and the missed list. `agent2/release.py` runs the gold-free format checks and dev-only scoring in one step. Then the downstream check: Agent 3 accuracy with ③ input vs raw record input.

## LLM calls

Use `gold_lib.call_llm(provider, model, prompt, temperature, max_tokens)`; it enforces a wall-clock deadline (`LLM_DEADLINE`, default 240 s) because OpenRouter streams keep-alive whitespace and can hang. Keep `max_tokens` bounded, validate every field type, re-ask only for invalid items. Default OpenRouter routing (provider sort `throughput` multiplies cost). Final runs use Claude Haiku 4.5 through the Batches API on the user's Mac (keys never in the workspace). Shell commands for the user: no `#` comments and no `!` (zsh).
