"""LLM clients for the judgment step. No SDK needed (plain HTTPS), keys come from env vars only.

  anthropic  Claude Messages API. ANTHROPIC_API_KEY, model e.g. claude-sonnet-5-5.
             The patient evidence block is sent with prompt caching, so the 2nd..nth trial of the
             same patient reuses it.
  openai     Any OpenAI-compatible /chat/completions endpoint (vLLM, gpt-oss-120b ...).
             OPENAI_API_KEY, OPENAI_BASE_URL.
  mock       No API call. Every criterion UNKNOWN/MISSING. For testing the pipeline only.
  replay     Only read responses saved in the cache; fail on a miss. For exact re-scoring.
  export     No API call. Writes every request to <cache>/export_requests.jsonl in Message Batches
             format (half price, no rate-limit loop). Submit it, then `python3 -m agent3.ingest`
             the results into the cache and re-run with --llm replay.

Keys: ANTHROPIC_API_KEY / OPENAI_API_KEY from the shell or from .env (agent3/env_setup.py, a3-0.3.1).

Every raw response is saved under the cache directory, keyed by model + prompt version + pair +
criterion ids, and reused on the next run, so a re-run after a code change costs nothing.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from .env_setup import load_env


class LLMError(RuntimeError):
    pass


def _post(url, headers, body, timeout=600):    # long replies (~4k tokens) can take minutes when the API is busy
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:300]
        if ex.code in (400, 401, 403, 404):          # not worth retrying
            raise LLMError(f"HTTP {ex.code}: {detail}") from None
        raise urllib.error.URLError(f"HTTP {ex.code}: {detail}")


def parse_json(text):
    """The first top-level JSON object in the reply (tolerates code fences and stray prose)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object")


class Judge:
    def __init__(self, provider, model, cache_dir, max_tokens=32000, temperature=None):
        if provider in ("anthropic", "openai"):
            load_env()                               # keys from .env (shell exports still win)
        self.provider, self.model = provider, model
        self.cache_dir = cache_dir
        self.max_tokens, self.temperature = max_tokens, temperature
        os.makedirs(cache_dir, exist_ok=True)
        self.usage = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

    # ------------------------------------------------------------------ public
    def cache_key(self, key_parts, criterion_ids, content=""):
        # the provider is not part of the key, so `replay` and `export`/ingest find the same file.
        # v2: the prompt text itself (system + patient + trial block) is hashed into the key. In v1 the key
        # was model + prompt version + pair + criterion ids only, so a new evidence file, new criteria or a
        # changed rule text silently replayed answers that were given to the old inputs.
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return hashlib.sha256(json.dumps([self.model, *key_parts, criterion_ids, digest]).encode()).hexdigest()[:24]

    def anthropic_body(self, system, patient_text, trial_text):
        return {
            "model": self.model, "max_tokens": self.max_tokens,
            **({"temperature": self.temperature} if self.temperature is not None else {}),
            "system": [{"type": "text", "text": system}],
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": patient_text, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": trial_text}]}],
        }

    def judge(self, key_parts, system, patient_text, trial_text, criterion_ids):
        key = self.cache_key(key_parts, criterion_ids, "\n".join([system, patient_text, trial_text]))
        path = os.path.join(self.cache_dir, key + ".json")
        if os.path.exists(path):
            self.usage["cache_hits"] += 1
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            return parse_json(saved["reply"])
        if self.provider == "replay":
            raise LLMError(f"replay: no cached response for {key_parts}")
        if self.provider in ("mock", "export"):
            if self.provider == "export":
                # one line per call in Message Batches API request format; answers come back via agent3.ingest
                with open(os.path.join(self.cache_dir, "export_requests.jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"custom_id": key, "params": self.anthropic_body(system, patient_text, trial_text),
                                        "meta": {"key_parts": key_parts, "criterion_ids": criterion_ids}},
                                       ensure_ascii=False) + "\n")
            return {"cohort_assignment": None, "results": [
                {"criterion_id": c, "applicable": True, "status": "UNKNOWN", "reason": "MISSING",
                 "evidence_ids": [], "action": None, "rule_tags": [self.provider], "note": self.provider} for c in criterion_ids]}

        last = None
        for attempt in range(3):
            try:
                reply = self._call(system, patient_text, trial_text)
                obj = parse_json(reply)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"key_parts": key_parts, "model": self.model, "criterion_ids": criterion_ids,
                               "reply": reply}, f, ensure_ascii=False)
                return obj
            except (ValueError, urllib.error.URLError, LLMError, KeyError, TimeoutError, ConnectionError) as ex:
                # a3-0.3.1: a read timeout (TimeoutError) used to escape this loop and stop the whole run
                last = ex
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"LLM failed for {key_parts}: {last}")

    # ------------------------------------------------------------------ providers
    def _call(self, system, patient_text, trial_text):
        self.usage["calls"] += 1
        if self.provider == "anthropic":
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise LLMError("ANTHROPIC_API_KEY is not set")
            body = self.anthropic_body(system, patient_text, trial_text)
            r = _post(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com") + "/v1/messages",
                      {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, body)
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                self.usage[k] += (r.get("usage") or {}).get(k) or 0
            if r.get("stop_reason") == "max_tokens":
                raise LLMError("reply cut at max_tokens")
            return "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")
        if self.provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "none")
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            body = {"model": self.model, "temperature": self.temperature or 0, "max_tokens": self.max_tokens,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": patient_text + "\n\n" + trial_text}]}
            r = _post(base + "/chat/completions", {"Authorization": f"Bearer {key}", "content-type": "application/json"}, body)
            u = r.get("usage") or {}
            self.usage["input_tokens"] += u.get("prompt_tokens") or 0
            self.usage["output_tokens"] += u.get("completion_tokens") or 0
            return r["choices"][0]["message"]["content"]
        raise LLMError(f"unknown provider {self.provider}")
