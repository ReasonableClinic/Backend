"""Optional Langfuse tracing shared by all agents. Off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set
(in .env or the shell) and the `langfuse` package (v5) is installed; otherwise every call is a no-op and the agent
runs exactly as before.

    from common.tracing import Tracer
    tr = Tracer.create(agent="agent3", run_id=run_id, version="a3-0.3.0", model="claude-sonnet-5-5")
    span = tr.llm(key="SYN-0001", name="judge NCT06110130", input={"prompt": p}, model="claude-sonnet-5-5")
    ...                                                   # the call
    span.end(output=text, usage={"input_tokens": 120, "output_tokens": 40}, cost=0.001)   # or span.end(error=e)
    tr.result(key="SYN-0001", output={"trial_label": "potential"}, scores={"n_unknown": 7})
    tr.finish()

Naming (team rule, so one patient's 1 -> 6 flow lines up across agents):
  trace     "<agent>:<key>"  key = patient_id for agents 2-6, trial_id for agent 1
  session   the run id (the pipeline passes one run id to every agent: RUN_ID in the environment)
  user      the key, tags [agent, model, TRACE_LABEL]
The trace id is derived from (run id, agent, key), so calls of one patient made in parallel threads land in one trace.

TRACE_CONTENT controls how much text leaves the machine: units/full (send input and output as given) | none (no text,
only counts, tokens, timings and scores). Use `none` or a self-hosted Langfuse for anything but synthetic records.
Generalised from agent2 v14.12 (agent2/tracing.py); agent2 keeps its own until the modularisation moves it here.
"""
import os, re, sys, threading, time


class _Off:
    enabled = False

    def __getattr__(self, name):                 # every method is a no-op that returns the same object,
        return lambda *a, **k: self              # so tr.llm(...).end(...) also works when tracing is off


def _ascii(s, n=200):
    return re.sub(r"[^\x20-\x7e]", "_", str(s))[:n]


class Tracer:
    enabled = False

    @classmethod
    def create(cls, agent, run_id=None, version=None, model=None, label=None):
        if os.environ.get("TRACING", "auto").lower() in ("0", "off", "false", "no"):
            return _Off()
        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return _Off()
        try:
            import langfuse  # noqa: F401
        except ImportError:
            print("  tracing: LANGFUSE keys are set but the 'langfuse' package is missing "
                  f"({sys.executable} -m pip install 'langfuse>=5,<6'); running without tracing", flush=True)
            return _Off()
        try:
            return cls(agent, run_id or os.environ.get("RUN_ID") or f"{agent}-{time.strftime('%Y%m%d-%H%M%S')}",
                       version, model, label or os.environ.get("TRACE_LABEL"))
        except Exception as e:  # noqa: BLE001  tracing must never stop a run
            print(f"  tracing: disabled ({type(e).__name__}: {str(e)[:200]})", flush=True)
            return _Off()

    def __init__(self, agent, run_id, version, model, label):
        from langfuse import Langfuse, propagate_attributes
        self._prop = propagate_attributes
        self.lf = Langfuse(environment=os.environ.get("TRACE_ENV", "dev"), release=version)
        self.enabled = True
        self.agent, self.run_id, self.version, self.model = agent, _ascii(run_id), version, model
        self.content = os.environ.get("TRACE_CONTENT", "units").lower()
        self.tags = list(dict.fromkeys(t for t in (agent, (model or "").split("/")[-1], label) if t))
        self.lock = threading.Lock()

    def trace_id(self, key):
        from langfuse import Langfuse
        return Langfuse.create_trace_id(seed=f"{self.run_id}:{self.agent}:{key}")

    def _attrs(self, key):
        return self._prop(user_id=_ascii(key), session_id=self.run_id, trace_name=_ascii(f"{self.agent}:{key}"),
                          tags=self.tags, version=self.version, metadata={"run": self.run_id[:190], "agent": self.agent})

    def _text(self, x):
        return x if self.content != "none" else {"chars": len(str(x or ""))}

    def llm(self, key, name, input=None, model=None, metadata=None, model_parameters=None):
        """Start a generation for one LLM call; returns a handle with .end(output=None, usage=None, cost=None, error=None)."""
        try:
            with self._attrs(key):
                g = self.lf.start_observation(trace_context={"trace_id": self.trace_id(key)}, as_type="generation",
                                              name=name, model=model or self.model, input=self._text(input),
                                              metadata=metadata, model_parameters=model_parameters)
        except Exception:  # noqa: BLE001
            return _Off()
        return _Handle(self, g, time.time())

    def step(self, key, name, input=None, output=None, metadata=None, warning=False):
        """A non-LLM step (rule pass, file write) recorded as a finished span."""
        try:
            with self._attrs(key):
                s = self.lf.start_observation(trace_context={"trace_id": self.trace_id(key)}, name=name,
                                              input=self._text(input), output=self._text(output), metadata=metadata,
                                              level="WARNING" if warning else None)
                s.end()
        except Exception:  # noqa: BLE001
            pass

    def result(self, key, output=None, scores=None, warning=False):
        """Per-key summary span plus numeric scores on the trace (compare runs in the Langfuse UI)."""
        self.step(key, f"{self.agent}_result", output=output, warning=warning)
        for name, value in (scores or {}).items():
            try:
                self.lf.create_score(name=name, value=float(value), data_type="NUMERIC", trace_id=self.trace_id(key))
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

    def end(self, output=None, usage=None, cost=None, error=None):
        try:
            u = usage or {}
            details = {k: int(v) for k, v in (("input", u.get("input_tokens")), ("output", u.get("output_tokens")),
                                                ("cache_read_input_tokens", u.get("cache_read_input_tokens")),
                                                ("cache_creation_input_tokens", u.get("cache_creation_input_tokens")),
                                                ("reasoning_tokens", u.get("reasoning_tokens"))) if v}
            kw = {"usage_details": details or None, "metadata": {"seconds": round(time.time() - self.t0, 2)}}
            if cost is not None:
                kw["cost_details"] = {"total": float(cost)}
            if error is not None:
                kw.update(level="ERROR", status_message=f"{type(error).__name__}: {str(error)[:300]}")
            else:
                kw["output"] = self.t._text(output)
            self.g.update(**{k: v for k, v in kw.items() if v is not None})
            self.g.end()
        except Exception:  # noqa: BLE001
            pass
