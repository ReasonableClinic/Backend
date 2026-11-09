"""Agent 3 - Eligibility Reasoner (common format v0.5).

Per patient-trial pair: judge every criterion as PASS / FAIL / UNKNOWN / CONFLICT with
evidence ids from Agent 2, aggregate the trial label with rule 6.1, and write the
Evidence Graph shared with Agents 4-6.

Code decides what code can decide (age, sex, impossible conditions, consent-type
administrative items, ①-b numeric / categorical criteria with their time windows,
OR / AND logic groups); an LLM judges the rest; code post-checks the LLM.
"""
VERSION = "a3-0.3.1"
