"""LLM backends for the Agent 2 LLM layer. Every backend takes a list of requests and returns {custom_id: text or
Exception}. A request is {"custom_id", "static", "patient", "units", "max_tokens"} (prompts.py parts).

  openrouter       development (default model openai/gpt-oss-120b), parts joined into one user message,
                   via gold_lib.call_llm (wall-clock deadline, real cost from OpenRouter)
  anthropic        Claude API, one request at a time (threads), prompt caching on the static and patient parts
  anthropic-batch  Claude Message Batches API (50% price), same caching breakpoints (1-hour TTL, best effort
                   inside a batch); submits once, polls, collects; the batch id is saved so a rerun resumes it
  mock             echoes the rule hints (plumbing test, no network)

All backends share a response cache on disk (<cache dir>/responses.jsonl, key = model + full prompt), so a rerun
with the same prompts calls nothing. Usage is summed per run, with a cost estimate from PRICES.
"""
import collections, hashlib, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "code"))
sys.path.insert(0, HERE)
from env_setup import load_env  # noqa: E402
load_env()                                          # API keys and settings from .env (shell exports still win)
from tracing import _Off  # noqa: E402
# speed defaults (set before gold_lib reads them); override by exporting the variable
os.environ.setdefault("LLM_DEADLINE", "120")        # requests are small now; a hung one is cut and retried sooner
os.environ.setdefault("REASONING_EFFORT", "low")    # gpt-oss on OpenRouter: less hidden reasoning, faster answers

# USD per million tokens (platform.claude.com/docs/en/about-claude/pricing, checked 2026-10-06).
# batch = 50% of input and output. Cache write 5m = 1.25x input, 1h = 2x input, cache read = 0.1x input.
PRICES = {"claude-haiku-4-5": {"input": 1.0, "output": 5.0}}
FATAL = {"AuthenticationError", "PermissionDeniedError", "NotFoundError"}


def key_of(model, req):
    raw = json.dumps([model, req["static"], req["patient"], req["units"]], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def joined(req):
    return "\n\n".join(x for x in (req["static"], req["patient"], req["units"]) if x)


class Backend:
    def __init__(self, provider, model, cache_dir, workers=4, ttl=None, poll=30):
        # prompt cache TTL: a batch may wait long between requests (1h); a direct call finishes within seconds, and
        # a 5-minute write costs 1.25x input instead of 2x
        ttl = ttl or ("1h" if provider == "anthropic-batch" else "5m")
        self.provider, self.model, self.workers, self.ttl, self.poll = provider, model, workers, ttl, poll
        self.warmed = set()
        self.usage = collections.Counter()
        self.no_temperature = bool(os.environ.get("AGENT2_NO_TEMPERATURE"))
        self.errors = []
        self.tracer = _Off()                # llm_layer sets a tracing.Tracer when Langfuse is configured
        self.seconds = []
        self.lock = threading.Lock()
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_path = os.path.join(cache_dir, "responses.jsonl")
        self.batch_state = os.path.join(cache_dir, "batches.json")
        self.cache = {}
        if os.path.exists(self.cache_path):
            for line in open(self.cache_path, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    self.cache[r["key"]] = r["text"]
        if provider in ("anthropic", "anthropic-batch"):
            import gold_lib as G
            G.preflight("anthropic")
            import anthropic
            base = os.environ.get("AGENT2_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
            self.client = anthropic.Anthropic(base_url=base, timeout=G.TIMEOUT, max_retries=2)
        elif provider == "replay":                # answers.jsonl of an earlier run, matched by custom_id
            self.replay = {}
            for line in open(os.environ["AGENT2_REPLAY"], encoding="utf-8"):
                r = json.loads(line)
                if r.get("answer"):
                    self.replay[r["custom_id"]] = r["answer"]
        elif provider == "openrouter":
            import gold_lib as G
            G.preflight("openrouter")
            self.G = G

    # ---------------------------------------------------------------- shared
    def _store(self, key, text):
        if self.provider == "replay":
            return
        with self.lock:
            self.cache[key] = text
            with open(self.cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "model": self.model, "text": text}, ensure_ascii=False) + "\n")

    def _add_usage(self, u, batch=False):
        with self.lock:
            self.usage["calls"] += 1
            if batch:
                self.usage["batch_calls"] += 1
            for k, v in (u or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    self.usage[("batch_" if batch else "") + k] += v

    def run(self, reqs):
        out, todo = {}, []
        for r in reqs:
            k = key_of(self.model, r)
            if k in self.cache:
                out[r["custom_id"]] = self.cache[k]
                self.usage["cache_hits_local"] += 1
            else:
                todo.append((k, r))
        if todo:
            if self.provider == "anthropic-batch":
                out.update(self._batch(todo))
            else:
                with ThreadPoolExecutor(max_workers=self.workers) as ex:
                    for cid, res in ex.map(self._one, todo):
                        out[cid] = res
        return out

    def _one(self, kr):
        k, r = kr
        t0 = time.time()
        span = self.tracer.request(r, self.model)
        try:
            if self.provider == "replay":
                if r["custom_id"] not in self.replay:
                    raise RuntimeError("not in the replay file")
                text, u = self.replay[r["custom_id"]], {}
            elif self.provider == "mock":
                text, u = mock_answer(r["units"]), {"input_tokens": len(joined(r)) // 4}
            elif self.provider == "openrouter":
                text, u = self.G.call_llm("openrouter", self.model, joined(r), 0.0, max_tokens=r["max_tokens"])
            else:
                params = self._params(r)
                if self.no_temperature:
                    params.pop("temperature", None)
                try:
                    m = self.client.messages.create(**params)
                except (TypeError, Exception) as e:  # some SDK versions / models reject temperature
                    if "temperature" not in str(e).lower() or "temperature" not in params:
                        raise
                    self.no_temperature = True
                    params.pop("temperature")
                    m = self.client.messages.create(**params)
                text = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
                u = _usage(m.usage)
            self._add_usage(u)
            with self.lock:
                self.seconds.append(time.time() - t0)
            self._store(k, text)
            span.end(text=text, usage=u)
            return r["custom_id"], text
        except Exception as e:  # noqa: BLE001
            span.end(error=e)
            if type(e).__name__ in FATAL:
                raise
            with self.lock:
                self.errors.append(f"{type(e).__name__}: {str(e)[:300]}")
            return r["custom_id"], e

    def prewarm(self, pairs):
        """Write the prompt cache before the parallel requests go out (direct Claude calls only; a batch cannot).
        pairs: [(static, patient_part)]. A request with max_tokens 0 writes the cache and returns no output; the
        requests sent after it read the cache instead of each writing their own copy."""
        if self.provider != "anthropic":
            return
        todo = [(st, pt) for st, pt in dict.fromkeys(pairs) if (st, pt) not in self.warmed]

        def one(pair):
            st, pt = pair
            params = self._params({"static": st, "patient": pt, "units": "warmup", "max_tokens": 0})
            params.pop("temperature", None)
            t0 = time.time()
            try:
                m = self.client.messages.create(**params)
                self._add_usage(_usage(m.usage))
                with self.lock:
                    self.usage["prewarm_calls"] += 1
                    self.usage["prewarm_seconds"] += round(time.time() - t0, 2)
                    self.warmed.add(pair)
            except Exception as e:  # noqa: BLE001  pre-warming is an optimization; never fail the run on it
                with self.lock:
                    self.errors.append(f"prewarm: {type(e).__name__}: {str(e)[:200]}")
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            list(ex.map(one, todo))

    def _params(self, r):
        cc = {"type": "ephemeral", "ttl": self.ttl} if self.ttl == "1h" else {"type": "ephemeral"}
        system = [{"type": "text", "text": r["static"], "cache_control": cc}]
        if r["patient"]:
            system.append({"type": "text", "text": r["patient"], "cache_control": cc})
        return {"model": self.model, "max_tokens": r["max_tokens"], "temperature": 0.0, "system": system,
                "messages": [{"role": "user", "content": r["units"]}]}

    # ---------------------------------------------------------------- batch
    def _batch(self, todo):
        """One Message Batch for all uncached requests. The batch id and its request keys are saved first, so if
        the script is stopped while waiting, the next run with the same prompts picks the same batch up."""
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        state = json.load(open(self.batch_state)) if os.path.exists(self.batch_state) else {}
        sig = hashlib.sha1("|".join(sorted(k for k, _ in todo)).encode()).hexdigest()[:16]
        by_cid = {r["custom_id"]: (k, r) for k, r in todo}
        if sig in state:
            bid = state[sig]
            print(f"  resuming batch {bid} ({len(todo)} requests)", flush=True)
        else:
            def params(r):
                x = self._params(r)
                if self.no_temperature:
                    x.pop("temperature", None)
                return x
            b = self.client.messages.batches.create(requests=[
                Request(custom_id=r["custom_id"], params=MessageCreateParamsNonStreaming(**params(r)))
                for _, r in todo])
            bid = b.id
            state[sig] = bid
            json.dump(state, open(self.batch_state, "w"), indent=1)
            print(f"  submitted batch {bid} ({len(todo)} requests); waiting (most finish within 1 hour)", flush=True)
        while True:
            b = self.client.messages.batches.retrieve(bid)
            if b.processing_status == "ended":
                break
            c = b.request_counts
            print(f"  batch {bid}: processing {c.processing}, succeeded {c.succeeded}, errored {c.errored}", flush=True)
            time.sleep(self.poll)
        out = {}
        for res in self.client.messages.batches.results(bid):
            cid = res.custom_id
            if cid not in by_cid:
                continue
            if res.result.type == "succeeded":
                m = res.result.message
                text = "".join(x.text for x in m.content if getattr(x, "type", "") == "text")
                self._add_usage(_usage(m.usage), batch=True)
                self._store(by_cid[cid][0], text)
                self.tracer.request(by_cid[cid][1], self.model, batch_id=bid).end(text=text, usage=_usage(m.usage))
                out[cid] = text
            else:
                err = getattr(res.result, "error", None)
                msg = f"batch result {res.result.type}: {str(err)[:300]}"
                self.errors.append(msg)
                self.tracer.request(by_cid[cid][1], self.model, batch_id=bid).end(error=RuntimeError(msg))
                if "temperature" in msg.lower():
                    self.no_temperature = True      # the retry round resubmits without it
                out[cid] = RuntimeError(msg)
        return out

    # ---------------------------------------------------------------- report
    def report(self):
        u = dict(self.usage)
        if self.seconds:
            x = sorted(self.seconds)
            u["request_seconds"] = {"p50": round(x[len(x) // 2], 1), "p90": round(x[min(len(x) - 1, int(len(x) * 0.9))], 1),
                                    "max": round(x[-1], 1)}
        p = next((v for k, v in PRICES.items() if self.model.startswith(k)), None)
        if p and self.provider.startswith("anthropic"):
            mult_write = 2.0 if self.ttl == "1h" else 1.25
            cost = 0.0
            for pre, f in (("", 1.0), ("batch_", 0.5)):
                cost += f * (u.get(pre + "input_tokens", 0) * p["input"]
                             + u.get(pre + "cache_creation_input_tokens", 0) * p["input"] * mult_write
                             + u.get(pre + "cache_read_input_tokens", 0) * p["input"] * 0.1
                             + u.get(pre + "output_tokens", 0) * p["output"]) / 1e6
            u["estimated_cost_usd"] = round(cost, 4)
        elif "cost" in u:
            u["openrouter_cost_usd"] = round(u.pop("cost"), 4)
        return u


def _usage(us):
    return {"input_tokens": us.input_tokens, "output_tokens": us.output_tokens,
            "cache_creation_input_tokens": getattr(us, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(us, "cache_read_input_tokens", 0) or 0}


def mock_answer(units_text):
    """Fake model: accepts the rule hint ("ok") of every unit that has one, leaves out the rest. With MOCK_TPS set
    (tokens per second), sleeps as long as a model writing that answer would, for rough latency simulations."""
    out, drop = [], []
    for line in units_text.splitlines():
        m = re.match(r"u(\d+) \|.*\| hint: (.+?)(?: \| your previous answer.*)?$", line)
        if m and m.group(2) != "-":
            out.append({"u": int(m.group(1)), "ok": True})
        elif m:
            drop.append(int(m.group(1)))
    text = json.dumps({"units": out, "drop": drop})
    if os.environ.get("MOCK_TRUNCATE") and len(out) > 4:    # simulate an answer cut off by the output limit
        text = text[:int(len(text) * float(os.environ["MOCK_TRUNCATE"]))]
    if os.environ.get("MOCK_TPS"):
        time.sleep(len(text) / 3.5 / float(os.environ["MOCK_TPS"]))
    return text
