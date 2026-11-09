"""Optional Langfuse tracing for the Agent 2 LLM layer. Off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are
set (in .env or the shell) and the `langfuse` package (v5) is installed; otherwise every call here is a no-op, so the
pipeline runs exactly as before.

What is recorded
  trace      one per patient per run: name "agent2:<patient_id>", user_id = patient_id, session_id = run id,
             tags [agent2, provider, model, dev/test/variant label]. The trace id is derived from (run id, patient id),
             so the requests of one patient land in one trace even though they run in parallel threads.
  generation one per LLM request (round, chunk): model, prompt parts, answer, tokens, cost, seconds, errors.
  score      answer_parse on each generation (ok / truncated / bad_json / request_failed), set after parsing.
  span       patient_result at the end: number of evidence, units with facts, and the patient's checks counter,
             plus numeric scores n_evidence and units_with_facts on the trace.

AGENT2_TRACE_CONTENT controls how much text leaves the machine:
  units (default)  the units part and the answer; the static instructions (~6k tokens, identical in every request)
                   and the candidate-criteria part are sent as a hash and length only
  full             every prompt part as sent
  none             no text at all, only counts, tokens, timings and scores
Use `none` (or a self-hosted Langfuse, LANGFUSE_BASE_URL) before running on anything but synthetic records.
"""
import hashlib, os, re, sys, threading, time

_CID = re.compile(r"^(?P<pid>.+)-r(?P<rnd>\d+)-c(?P<chunk>\d+)$")


def _h(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


class _Off:
    enabled = False

    def __getattr__(self, name):                 # every method is a no-op that returns the same object,
        return lambda *a, **k: self              # so tracer.request(...).end(...) also works when tracing is off


class Tracer:
    enabled = False

    @classmethod
    def create(cls, run_id, provider, model, label=None, version=None):
        if os.environ.get("AGENT2_TRACING", "auto").lower() in ("0", "off", "false", "no"):
            return _Off()
        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return _Off()
        try:
            from langfuse import Langfuse, propagate_attributes  # noqa: F401
        except ImportError:
            print("  tracing: LANGFUSE keys are set but the 'langfuse' package is missing "
                  f"({sys.executable} -m pip install 'langfuse>=5,<6'); running without tracing", flush=True)
            return _Off()
        try:
            return cls(run_id, provider, model, label, version)
        except Exception as e:  # noqa: BLE001  tracing must never stop a run
            print(f"  tracing: disabled ({type(e).__name__}: {str(e)[:200]})", flush=True)
            return _Off()

    def __init__(self, run_id, provider, model, label, version):
        from langfuse import Langfuse, propagate_attributes
        self._prop = propagate_attributes
        self.lf = Langfuse(environment=os.environ.get("AGENT2_TRACE_ENV", "dev"), release=version)
        self.enabled = True
        self.run_id = re.sub(r"[^\x20-\x7e]", "_", run_id)[:200]
        self.provider, self.model, self.label, self.version = provider, model, label, version
        self.content = os.environ.get("AGENT2_TRACE_CONTENT", "units").lower()
        self.obs = {}                     # custom_id -> (trace_id, observation_id)
        self.lock = threading.Lock()
        self.tags = list(dict.fromkeys(t for t in ("agent2", provider, (model or "").split("/")[-1], label) if t))

    # ------------------------------------------------------------------ helpers
    def trace_id(self, pid):
        from langfuse import Langfuse
        return Langfuse.create_trace_id(seed=f"{self.run_id}:{pid}")

    def _attrs(self, pid):
        return self._prop(user_id=str(pid)[:200], session_id=self.run_id, trace_name=f"agent2:{pid}"[:200],
                          tags=self.tags, version=self.version,
                          metadata={"run": self.run_id[:190], "provider": self.provider})

    def _input(self, req):
        if self.content == "none":
            return {"units_chars": len(req.get("units") or "")}
        x = {"units": req.get("units")}
        for part in ("static", "patient"):
            t = req.get(part) or ""
            if self.content == "full":
                x[part] = t
            else:
                x[part] = {"sha1": _h(t), "chars": len(t)} if t else None
        return x

    # ------------------------------------------------------------------ per request
    def request(self, req, model, batch_id=None):
        """Start a generation for one request; returns a handle with .end(text=None, usage=None, error=None)."""
        m = _CID.match(req["custom_id"])
        pid = m.group("pid") if m else req["custom_id"]
        meta = {"custom_id": req["custom_id"], "round": int(m.group("rnd")) + 1 if m else None,
                "chunk": int(m.group("chunk")) if m else None,
                "n_units": sum(1 for line in (req.get("units") or "").splitlines() if re.match(r"u\d+ \|", line)),
                "static_sha1": _h(req.get("static")), "patient_part_sha1": _h(req.get("patient"))}
        if batch_id:
            meta["batch_id"] = batch_id
        try:
            with self._attrs(pid):
                g = self.lf.start_observation(
                    trace_context={"trace_id": self.trace_id(pid)}, as_type="generation",
                    name=f"extract r{meta['round']} c{meta['chunk']}" if m else "extract",
                    model=model, input=self._input(req), metadata=meta,
                    model_parameters={"max_tokens": req.get("max_tokens"), "temperature": 0.0})
            with self.lock:
                self.obs[req["custom_id"]] = (g.trace_id, g.id)
        except Exception:  # noqa: BLE001
            return _Off()
        return _Handle(self, g, time.time())

    def mark(self, custom_id, outcome, comment=None):
        """answer_parse score on the request's generation, after llm_layer has parsed the answer."""
        ids = self.obs.get(custom_id)
        if not ids:
            return
        try:
            self.lf.create_score(name="answer_parse", value=outcome, data_type="CATEGORICAL",
                                 trace_id=ids[0], observation_id=ids[1], comment=(comment or "")[:500] or None)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ per patient
    def patient_result(self, log):
        pid = log["patient_id"]
        try:
            tid = self.trace_id(pid)
            with self._attrs(pid):
                s = self.lf.start_observation(
                    trace_context={"trace_id": tid}, name="patient_result",
                    output={k: log.get(k) for k in ("n_units", "units_with_facts", "n_evidence", "seconds", "checks")},
                    metadata={"candidate_trials": [t for t, _ in ((log.get("plan") or {}).get("candidate_trials") or [])][:20]},
                    level="WARNING" if any(log["checks"].get(k) for k in ("request_failed", "bad_json")) else None)
                s.end()
            for name in ("n_evidence", "units_with_facts"):
                self.lf.create_score(name=name, value=float(log.get(name) or 0), data_type="NUMERIC", trace_id=tid)
        except Exception:  # noqa: BLE001
            pass

    def finish(self):
        try:
            self.lf.flush()
            host = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"
            print(f"  tracing: flushed to {host}, session {self.run_id} (connection errors, if any, are printed above)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  tracing: flush failed ({type(e).__name__}: {str(e)[:200]})", flush=True)


class _Handle:
    def __init__(self, tracer, gen, t0):
        self.t, self.g, self.t0 = tracer, gen, t0

    def end(self, text=None, usage=None, error=None):
        try:
            u = usage or {}
            details = {k: int(v) for k, v in (("input", u.get("input_tokens")), ("output", u.get("output_tokens")),
                                                ("cache_read_input_tokens", u.get("cache_read_input_tokens")),
                                                ("cache_creation_input_tokens", u.get("cache_creation_input_tokens")),
                                                ("reasoning_tokens", u.get("reasoning_tokens"))) if v}
            kw = {"usage_details": details or None}
            if u.get("cost") is not None:                       # OpenRouter reports the real charged cost
                kw["cost_details"] = {"total": float(u["cost"])}
            if error is not None:
                kw.update(level="ERROR", status_message=f"{type(error).__name__}: {str(error)[:300]}")
            elif self.t.content != "none":
                kw["output"] = text
            else:
                kw["output"] = {"chars": len(text or "")}
            self.g.update(**{k: v for k, v in kw.items() if v is not None},
                          metadata={"seconds": round(time.time() - self.t0, 2)})
            self.g.end()
        except Exception:  # noqa: BLE001
            pass
